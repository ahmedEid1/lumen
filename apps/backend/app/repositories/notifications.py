from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.notification import Notification, NotificationKind
from app.models.user import User
from app.schemas.notification_prefs import NotificationDispatch
from app.services import notification_prefs as prefs_service

log = get_logger(__name__)


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    kind: NotificationKind,
    title: str,
    body: str = "",
    data: dict[str, Any] | None = None,
) -> Notification | None:
    """Create a notification, dispatch-aware.

    Phase D4: the user's per-kind preference governs four outcomes:

    - ``off``    → no row is written, no email is sent. Returns ``None``.
    - ``in_app`` → write the row, no email (pre-D4 behaviour). Default.
    - ``email_immediate`` → write the row AND enqueue a one-shot email.
    - ``digest_daily`` → write the row; the daily digest worker
      bundles unread ``digest_daily`` rows into one summary email.

    The Celery enqueue is best-effort (broker may be down in dev); the
    in-app row is the source of truth, so a failed enqueue must not
    block the calling write.
    """
    user = await db.get(User, user_id)
    if user is None:
        # Defensive: if the caller passed a stale user_id we still
        # write the row so the bug surfaces in the bell rather than
        # silently dropping data. This branch shouldn't fire because
        # every notification callsite holds a User reference.
        n = Notification(user_id=user_id, kind=kind, title=title, body=body, data=data or {})
        db.add(n)
        await db.flush()
        return n

    dispatch = prefs_service.resolve_dispatch(user, kind)
    if dispatch is NotificationDispatch.off:
        return None

    n = Notification(user_id=user_id, kind=kind, title=title, body=body, data=data or {})
    db.add(n)
    await db.flush()

    if dispatch is NotificationDispatch.email_immediate:
        _enqueue_immediate_email(user=user, notification=n)

    return n


def _enqueue_immediate_email(*, user: User, notification: Notification) -> None:
    """Best-effort one-shot email send via the email worker."""
    try:
        # Local import to avoid pulling Celery into request-time imports
        # in tests/dev runs that don't have a broker available.
        from app.workers.tasks.email import send as send_email_task

        subject = f"[Lumen] {notification.title}"
        text = notification.body or notification.title
        send_email_task.delay(user.email, subject, text)
    except Exception:  # pragma: no cover — broker outages in dev
        log.warning(
            "immediate_email_enqueue_failed",
            user_id=user.id,
            notification_id=notification.id,
            kind=notification.kind,
        )


async def list_for_user(db: AsyncSession, user_id: str, *, limit: int = 50) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def mark_read(db: AsyncSession, notification: Notification) -> None:
    if not notification.read_at:
        notification.read_at = datetime.now(UTC)
        # Explicit flush (session is autoflush=False) so a same-session
        # read after this call — e.g. a future composite handler that also
        # counts unread — sees the new state, matching repo.create.
        await db.flush()


async def mark_all_read_for_user(db: AsyncSession, *, user_id: str) -> int:
    """Set read_at on every currently-unread notification owned by user.

    Uses a single UPDATE so it's O(1) round-trips regardless of how many
    notifications the learner has accumulated. Returns the rowcount so
    the caller (and the UI badge) can react without a follow-up GET.
    """
    res = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return int(res.rowcount or 0)


async def mark_unread(db: AsyncSession, notification: Notification) -> None:
    """Two-way counterpart of :func:`mark_read` — clears ``read_at``.

    Deliberately does NOT touch ``digested_at``: the digest worker bundles
    on ``read_at IS NULL AND digested_at IS NULL``, so a row the user
    re-flags as unread after it was already emailed stays out of the next
    digest (no double-delivery).
    """
    if notification.read_at:
        notification.read_at = None
        await db.flush()  # see mark_read — same same-session-read rationale


async def delete_for_user(db: AsyncSession, *, user_id: str, notification_id: str) -> bool:
    """Hard-delete one notification iff owned by ``user_id``.

    Single statement — the ownership gate lives in the WHERE so a foreign
    id and a missing id are indistinguishable (rowcount 0 → the API layer
    404s without leaking existence). Hard delete is deliberate: CLAUDE.md
    reserves soft-delete for Course/Lesson/Review; notifications are
    ephemeral observability (the ``security.*`` admin alarms have a durable
    ``auth.refresh_reuse`` audit row as their system of record).
    """
    res = await db.execute(
        delete(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    return bool(res.rowcount)


async def clear_for_user(db: AsyncSession, *, user_id: str, scope: str = "read") -> int:
    """Bulk hard-delete scoped to the calling user — one DELETE statement.

    ``scope='read'`` (the UI default) only removes rows already read, so a
    backed-up inbox can be cleaned without destroying anything actionable;
    ``scope='all'`` is the explicit opt-in that empties everything.

    Digest interplay: digest-pending rows are by definition unread, so the
    default scope can never swallow an item the 07:00 digest hasn't emailed
    yet. ``scope='all'`` can — accepted: the user explicitly discarded the
    rows, and the in-app row is the source of truth (Phase D4 contract).
    """
    stmt = delete(Notification).where(Notification.user_id == user_id)
    if scope == "read":
        stmt = stmt.where(Notification.read_at.is_not(None))
    res = await db.execute(stmt)
    return int(res.rowcount or 0)


async def unread_count_for_user(db: AsyncSession, *, user_id: str) -> int:
    """COUNT of unread rows — served by ``ix_notifications_user_unread``
    (partial index, 0053) so the 60s badge poll stays O(unread)."""
    res = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(res.scalar() or 0)


async def list_page_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    cursor: str | None = None,
    limit: int = 20,
    unread_only: bool = False,
) -> tuple[list[Notification], str | None]:
    """Cursor-paginated history — the path past the bare list's newest-50 cap.

    Keyset pagination in ``(created_at DESC, id DESC)`` order with the id
    tiebreaker, mirroring ``moderation.list_reports``: ``notify_admins``
    fan-outs and same-transaction writes share a ``created_at`` instant, so
    ordering on the timestamp alone would page non-deterministically. The
    cursor is the id of the last row from the previous page; an anchor that
    doesn't exist (deleted mid-scroll) or isn't the caller's row degrades to
    the first page rather than erroring.

    Returns ``(rows, next_cursor)`` — ``next_cursor`` is ``None`` exactly
    when the page is the last one (we peek one row past ``limit``).
    """
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if cursor is not None:
        anchor = await db.get(Notification, cursor)
        if anchor is not None and anchor.user_id == user_id:
            stmt = stmt.where(
                or_(
                    Notification.created_at < anchor.created_at,
                    and_(
                        Notification.created_at == anchor.created_at,
                        Notification.id < anchor.id,
                    ),
                )
            )
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].id
    return rows, next_cursor
