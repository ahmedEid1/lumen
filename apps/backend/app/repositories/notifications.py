from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
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
