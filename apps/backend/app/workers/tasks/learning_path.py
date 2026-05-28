"""Monthly learning-path re-planner (Phase I5).

Walks every user with an active ``learning_paths`` row whose
``replanned_at`` is older than 30 days and calls
``learning_path.replan_for_user`` against each one. Per-user errors
are logged and swallowed — one learner's path failing must never
stop us re-planning the rest of the cohort.

Scheduled via Celery Beat at 04:00 UTC on the first of every month
(``app.workers.celery_app``). On a typical 100-learner cohort the
job touches the metered LLM provider ~100 times in 5-10 minutes;
the H1 cost meter rolls each call up under the
``learning_path.build`` feature and the budget guard short-circuits
any individual learner who is somehow over-spent.

The job is conservative about state. We compute the staleness
filter once at job start and snapshot the candidate user-id list
before touching any of them. A path that gets manually re-planned
mid-job (via the ``/learning-path/replan`` endpoint) is harmless
to re-plan again — the only side effect is one extra metered LLM
call and a freshly-archived previous "active" row.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db import base as db_base
from app.models.learning_path import PATH_STATUS_ACTIVE, LearningPath
from app.services import learning_path as learning_path_service
from app.workers.celery_app import celery

log = get_logger(__name__)


# How stale a path has to be before the beat job re-plans it.
# Tuned to the monthly cadence the spec calls for — paths re-planned
# in the last 30 days are skipped so a learner who triggered a
# manual replan two weeks ago doesn't get clobbered.
STALE_AFTER_DAYS = 30


async def _stale_user_ids(db: AsyncSession, *, cutoff: datetime) -> list[str]:
    """Return user ids whose active path has not been re-planned recently.

    Reads from the partial-unique-indexed ``status='active'`` rows
    so we only return at most one ``user_id`` per learner.
    """
    stmt = select(LearningPath.user_id).where(
        LearningPath.status == PATH_STATUS_ACTIVE,
        LearningPath.replanned_at < cutoff,
    )
    return [row[0] for row in (await db.execute(stmt)).all()]


async def _replan_one(db: AsyncSession, *, user_id: str) -> bool:
    """Replan one learner. Returns True on success, False on swallowed error.

    We catch every exception (not just AppError) because the failure
    mode "one user's path crashed the entire monthly job" is the
    worst outcome — better to log loudly and continue than block
    everyone else.
    """
    try:
        path = await learning_path_service.replan_for_user(db, user_id=user_id)
        if path is None:
            log.info("replan_skipped_no_active", user_id=user_id)
            return False
        await db.commit()
        log.info(
            "replan_succeeded",
            user_id=user_id,
            path_id=path.id,
            step_count=len(path.steps),
        )
        return True
    except Exception:
        await db.rollback()
        log.exception("replan_failed", user_id=user_id)
        return False


async def replan_paths_monthly_async() -> int:
    """Async core — re-plan every stale path. Returns the count succeeded.

    Each learner gets a fresh session so a rollback on one learner's
    failure can't poison a successful commit on the next. The
    candidate snapshot is captured in a separate session up front
    so the loop doesn't hold a long-running read lock.
    """
    cutoff = datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS)
    # Per-task NullPool engine — safe under the Celery worker's
    # fresh-per-task asyncio.run loop, where the shared pooled engine
    # raises "got Future attached to a different loop". One engine for
    # the task; each learner still gets its own session below. See
    # app.db.base.worker_session_scope.
    async with db_base.worker_session_scope() as Session:
        async with Session() as snap_session:
            candidates = await _stale_user_ids(snap_session, cutoff=cutoff)
        if not candidates:
            log.info("replan_monthly_no_candidates")
            return 0

        succeeded = 0
        for user_id in candidates:
            async with Session() as session:
                ok = await _replan_one(session, user_id=user_id)
                if ok:
                    succeeded += 1
        log.info(
            "replan_monthly_done",
            candidates=len(candidates),
            succeeded=succeeded,
        )
        return succeeded


@celery.task(
    name="app.workers.tasks.learning_path.replan_paths_monthly",
    # No autoretry — we already swallow per-user errors, and a
    # job-level failure (e.g. broker hiccup mid-run) is best handled
    # by the next monthly tick rather than an immediate retry that
    # would re-spend tokens on every learner the first pass touched.
)
def replan_paths_monthly() -> int:
    """Celery entry point. Returns the count of successful re-plans."""
    return asyncio.run(replan_paths_monthly_async())
