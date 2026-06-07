"""Notifications retention prune (notifications feature-completeness batch).

The ``notifications`` table previously grew without bound — the only purge
was the FK ``ondelete=CASCADE`` on user deletion. With delete/clear now in
the product, retention closes the lifecycle: a **read** row older than
``settings.notification_retention_days`` (default 90d) is hard-deleted by
this daily beat task. Unread rows are kept regardless of age — they may
still be actionable, and the user has explicit clear/delete controls if
they disagree.

Digest interplay (why this can't race ``digest.send_daily_digests``): the
digest bundles rows where ``read_at IS NULL AND digested_at IS NULL`` —
i.e. digest-pending rows are by definition *unread*, and this prune only
ever touches *read* rows. No carve-out needed.

Best-effort semantics, same shape as the digest worker: per-task NullPool
engine via ``worker_session_scope``, one bounded DELETE, idempotent against
an empty/no-expired state. A missed tick just means rows live a day longer.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import base as db_base
from app.models.notification import Notification
from app.workers.celery_app import celery

log = get_logger(__name__)


async def prune_notifications_async() -> int:
    """Delete read notifications older than the retention window.

    Returns the number of rows removed (for tests + the beat log line).
    """
    retention_days = get_settings().notification_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with db_base.worker_session_scope() as Session, Session() as db:
        res = await db.execute(
            delete(Notification).where(
                Notification.read_at.is_not(None),
                Notification.created_at < cutoff,
            )
        )
        await db.commit()
        pruned = int(res.rowcount or 0)
    log.info(
        "notifications_pruned",
        pruned=pruned,
        retention_days=retention_days,
    )
    return pruned


@celery.task(
    name="app.workers.tasks.notifications_prune.prune_notifications",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def prune_notifications() -> int:
    """Celery entry point. Returns the number of rows pruned."""
    return asyncio.run(prune_notifications_async())
