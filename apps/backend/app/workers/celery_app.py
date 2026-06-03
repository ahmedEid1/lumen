"""Celery app for background work."""

from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, install_value_redaction
from app.core.prod_guards import assert_byok_kek_present

_s = get_settings()
_log = get_logger(__name__)

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
        # Phase I5 — monthly learning-path re-planner. Registered
        # here so the worker boots with the task module imported;
        # the actual schedule entry lives below in ``beat_schedule``.
        "app.workers.tasks.learning_path",
        # L21a — tutor streaming task + sweep + orphan cleanup.
        # The task only fires when the new streaming POST handler
        # enqueues, which itself is gated on feature_tutor_streaming
        # (default OFF until L21b). The sweep + cleanup beat jobs
        # below run unconditionally — they're idempotent against an
        # empty table / no-orphan state.
        "app.workers.tasks.tutor_streaming",
        "app.workers.tasks.tutor_sweep",
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
    # Phase I5 — monthly learning-path re-planner. Runs at 04:00 UTC
    # on the first of every month so the spike in metered LLM
    # traffic lands well before any working-hours user load. The
    # task swallows per-user errors so a single failed learner
    # can't block the rest of the cohort.
    "replan-learning-paths": {
        "task": "app.workers.tasks.learning_path.replan_paths_monthly",
        "schedule": crontab(hour="4", minute="0", day_of_month="1"),
    },
    # L21a — tutor turn lifecycle housekeeping. Two sweep schedules
    # (10 s for pending, 30 s for running/streaming) so a clean
    # broker-down POST sees a definitive failure within ~12 s of
    # polling status (plan-v7 §P1-3). Orphan stream cleanup is far
    # less hot — every 5 min. timedelta(seconds=N) is the correct
    # sub-minute schedule shape (plan-v7 §V7-F10 caught `crontab(
    # second='*/10')` being invalid).
    "tutor-sweep-dead-turns": {
        "task": "tutor.sweep_dead_turns.v1",
        "schedule": timedelta(seconds=10),
        "options": {"expires": 30},
    },
    "tutor-cleanup-orphan-streams": {
        "task": "tutor.cleanup_orphan_streams.v1",
        "schedule": timedelta(minutes=5),
    },
}


def _on_worker_process_init() -> None:
    """Worker boot guard (S7-pre.6 / DR-7, R-S3).

    Runs in every forked worker process. It (1) installs the value-level
    redaction filter so worker structlog/exception sinks scrub secrets the
    same way the API does (R-S1′f / R-U3), and (2) runs the BYOK KEK boot
    guard so the worker — which is part of the KEK trust boundary, since the
    streaming tutor decrypts there — refuses to boot in production, or
    whenever an encrypted credential/brief row exists, without a real KEK.

    Raising here aborts the worker process boot (correct: a worker that
    cannot decrypt stored secrets must not silently run).
    """
    # Gate-B robustness fix: configure structlog EXPLICITLY before installing
    # the redaction processor. Without this, install_value_redaction() relies
    # on structlog's *default* processor list happening to end in a renderer —
    # true today, but a silent-breakage trap if worker logging ever diverges.
    configure_logging()
    install_value_redaction()
    problems: list[str] = []
    assert_byok_kek_present(get_settings(), problems)
    if problems:
        _log.error("worker_boot_guard_failed", problems=problems)
        raise RuntimeError("Celery worker boot guard refused to start: " + "; ".join(problems))


@worker_process_init.connect
def _worker_process_init_handler(**_kwargs) -> None:  # pragma: no cover - signal shim
    _on_worker_process_init()
