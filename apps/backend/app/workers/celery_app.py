"""Celery app for background work."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_s = get_settings()

celery = Celery(
    "lumen",
    broker=_s.celery_broker_url,
    backend=_s.celery_result_backend,
    include=[
        "app.workers.tasks.email",
        "app.workers.tasks.media",
        "app.workers.tasks.certificates",
        "app.workers.tasks.digest",
        "app.workers.tasks.embeddings",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_default_retry_delay=30,
    task_default_max_retries=5,
)

celery.conf.beat_schedule = {
    "sweep-unclaimed-assets": {
        "task": "app.workers.tasks.media.sweep_unclaimed_assets",
        "schedule": crontab(hour="3", minute="0"),
    },
    # Phase D4 — bundle yesterday's ``digest_daily`` notifications into
    # one summary email per user. 07:00 UTC is early enough to land in
    # most inboxes before the working day in EU/India and late enough
    # to capture overnight activity from the Americas. The task itself
    # is idempotent (``digested_at`` stamp gates re-delivery), so the
    # exact tick is a soft target.
    "send-daily-digests": {
        "task": "app.workers.tasks.digest.send_daily_digests",
        "schedule": crontab(hour="7", minute="0"),
    },
}
