"""Daily-digest worker (Phase D4).

For each user with at least one notification kind set to
``digest_daily``, this task bundles their undelivered + unread
notifications into a single summary email and stamps ``digested_at``
on every row included in that send so subsequent runs skip them.

Scheduling: Celery Beat fires this once per day at 07:00 UTC. The
schedule is registered in :mod:`app.workers.celery_app`.

Best-effort semantics: the in-app bell remains the source of truth.
If the broker or SMTP is down, the rows simply stay un-digested and
get picked up on the next successful run — no double-send (because of
the ``digested_at`` stamp) and no data loss (because the rows already
exist in ``notifications`` from the original write).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db import base as db_base
from app.models.notification import Notification, NotificationKind
from app.models.user import User
from app.schemas.notification_prefs import NotificationDispatch
from app.services import notification_prefs as prefs_service
from app.workers.celery_app import celery

log = get_logger(__name__)


def _digest_kinds_for(user: User) -> set[NotificationKind]:
    """Kinds the user wants delivered via the daily digest."""
    prefs = prefs_service.get_prefs(user)
    return {kind for kind, mode in prefs.items() if mode is NotificationDispatch.digest_daily}


def _render_digest(user: User, notifications: list[Notification]) -> tuple[str, str, str]:
    """Build (subject, text, html) for one user's bundled summary."""
    count = len(notifications)
    subject = f"[Lumen] Your daily digest — {count} new notification{'s' if count != 1 else ''}"
    name = user.full_name or user.email

    lines: list[str] = [f"Hi {name},", "", f"You have {count} new notification(s):", ""]
    for n in notifications:
        lines.append(f"- [{n.kind}] {n.title}")
        if n.body:
            lines.append(f"    {n.body}")
    lines.extend(["", "Open Lumen to act on these: visit your notifications page."])
    text = "\n".join(lines)

    rows_html = "\n".join(
        f"<li><strong>[{n.kind}]</strong> {n.title}"
        + (f'<br/><span style="color:#475569;">{n.body}</span>' if n.body else "")
        + "</li>"
        for n in notifications
    )
    html = (
        f"<p>Hi {name},</p>"
        f"<p>You have {count} new notification(s):</p>"
        f"<ul>{rows_html}</ul>"
        "<p>Open Lumen to act on these.</p>"
    )
    return subject, text, html


async def _collect_pending(
    db: AsyncSession, *, user: User, kinds: Iterable[NotificationKind]
) -> list[Notification]:
    """Unread + not-yet-digested rows for this user, restricted to digest kinds."""
    kind_values = [k.value for k in kinds]
    if not kind_values:
        return []
    stmt = (
        select(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.digested_at.is_(None),
            Notification.read_at.is_(None),
            Notification.kind.in_(kind_values),
        )
        .order_by(Notification.created_at.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def _run_digests(db: AsyncSession) -> int:
    """Core async loop — returns the number of digest emails sent."""
    # Candidate set: every user who has *anything* in their prefs
    # JSONB. Scanning users once a day is cheap; the alternative is a
    # functional index on ``jsonb_typeof`` which isn't worth the
    # migration cost. We filter the actual digest-kind check in Python
    # via :func:`_digest_kinds_for`.
    res = await db.execute(select(User))
    users = [u for u in res.scalars().all() if u.notification_prefs]

    sent = 0
    for user in users:
        digest_kinds = _digest_kinds_for(user)
        if not digest_kinds:
            continue
        pending = await _collect_pending(db, user=user, kinds=digest_kinds)
        if not pending:
            continue
        subject, text, html = _render_digest(user, pending)
        now = datetime.now(UTC)
        try:
            from app.workers.tasks.email import send as send_email_task

            send_email_task.delay(user.email, subject, text, html)
        except Exception:  # pragma: no cover — broker may be down in dev
            log.warning(
                "digest_email_enqueue_failed",
                user_id=user.id,
                pending=len(pending),
            )
            # Leave rows un-stamped so the next run retries.
            continue

        # Statement-level UPDATE rather than ORM attribute mutation: the
        # user can now hard-delete a notification (delete/clear endpoints)
        # between our SELECT and this stamp, and an ORM flush over a
        # vanished row raises StaleDataError — an UPDATE that matches 0
        # rows is simply a no-op for that row. Last writer wins, both
        # paths stay best-effort (no cross-transaction locking).
        await db.execute(
            update(Notification)
            .where(Notification.id.in_([n.id for n in pending]))
            .values(digested_at=now)
        )
        sent += 1
        log.info(
            "digest_sent",
            user_id=user.id,
            notification_count=len(pending),
        )
    await db.commit()
    return sent


async def send_daily_digests_async() -> int:
    """Entry point usable directly from async tests."""
    # Per-task NullPool engine — safe under the Celery worker's
    # fresh-per-task asyncio.run loop. See app.db.base.worker_session_scope.
    async with db_base.worker_session_scope() as Session, Session() as db:
        return await _run_digests(db)


@celery.task(
    name="app.workers.tasks.digest.send_daily_digests",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_daily_digests() -> int:
    """Celery entry point. Returns the number of digest emails sent."""
    return asyncio.run(send_daily_digests_async())
