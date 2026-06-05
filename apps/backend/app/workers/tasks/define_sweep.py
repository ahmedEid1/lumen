"""Define-and-build beat sweeps (S3.10 / DR-1b / FR-DEFINE-14b).

Two idempotent reapers that keep abandoned self-serve-build artifacts from
accumulating, mirroring the verified ``tutor_sweep`` task shape (per-task NullPool
engine via :func:`make_worker_engine`, batched ``FOR UPDATE SKIP LOCKED``, engine
disposed in ``finally``):

* :func:`sweep_orphaned_build_drafts` — soft-deletes (``deleted_at``) a course
  that is a self-serve-build artifact the owner never opened and is older than the
  retention window. "Build artifact" = ``status=build_failed`` (a failed/cancelled
  build) OR a ``draft`` course linked to a learning brief (an AI build the learner
  walked away from). "Never opened" = no ``lesson_progress`` row for any of the
  owner's enrollments in that course (the simplest verifiable signal). A recently
  created/opened draft is left alone, so a learner mid-define is never reaped.

* :func:`sweep_unfinalized_briefs` — hard-deletes a ``LearningBrief`` whose
  ``finalized_at IS NULL`` and is older than the retention window (DR-1b). A
  finalized brief (immutable build input, kept for provenance) and a recent
  un-finalized one (still being defined) are untouched. Briefs have no
  soft-delete column, so this is a hard delete of the (encrypted) goal artifact —
  which also satisfies the privacy posture (no orphaned ciphertext lingers).

Both are idempotent against empty / already-swept state (CLAUDE.md: Celery is
best-effort in dev). Background beat uses the PLATFORM model context (DR-8) — but
these sweeps make NO LLM calls, so there is no BYOK concern. The async helpers are
exposed (``_sweep_*_async``) and return the processed count so tests can drive
them directly and assert idempotency.
"""

from __future__ import annotations

import asyncio
import contextlib

from celery.utils.log import get_task_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.base import make_worker_engine
from app.workers.celery_app import celery

log = get_task_logger(__name__)

#: Per-sweep batch ceiling — bounds the lock footprint on a large backlog; the
#: beat re-fires daily so a backlog drains over a few ticks.
_BATCH = 200


@celery.task(name="define.sweep_orphaned_build_drafts.v1", bind=True, max_retries=0)
def sweep_orphaned_build_drafts(self) -> None:  # pragma: no cover - thin celery shim
    """Soft-delete abandoned, never-opened build drafts older than the window."""
    count = asyncio.run(_sweep_orphaned_build_drafts_async())
    log.info("define_sweep_orphaned_build_drafts_done", extra={"soft_deleted": count})


async def _sweep_orphaned_build_drafts_async() -> int:
    settings = get_settings()
    retention_days = int(settings.orphan_build_draft_retention_days)
    engine = make_worker_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT c.id
                        FROM courses c
                        WHERE c.deleted_at IS NULL
                          AND c.created_at < NOW() - make_interval(days => :days)
                          AND (
                                c.status = 'build_failed'
                                OR (
                                    c.status = 'draft'
                                    AND EXISTS (
                                        SELECT 1 FROM course_draft_traces t
                                        WHERE t.course_id = c.id
                                          AND t.payload ? 'brief_id'
                                    )
                                )
                          )
                          AND NOT EXISTS (
                                SELECT 1
                                FROM enrollments e
                                JOIN lesson_progress lp ON lp.enrollment_id = e.id
                                WHERE e.course_id = c.id
                                  AND e.user_id = c.owner_id
                          )
                        ORDER BY c.created_at
                        LIMIT :batch
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"days": retention_days, "batch": _BATCH},
                )
            ).fetchall()

            if not rows:
                return 0
            ids = [r.id for r in rows]
            await db.execute(
                text(
                    "UPDATE courses SET deleted_at = NOW() "
                    "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                ),
                {"ids": ids},
            )
            await db.commit()
            return len(ids)
    finally:
        with contextlib.suppress(Exception):
            await engine.dispose()


@celery.task(name="define.sweep_unfinalized_briefs.v1", bind=True, max_retries=0)
def sweep_unfinalized_briefs(self) -> None:  # pragma: no cover - thin celery shim
    """Hard-delete un-finalized learning briefs older than the window."""
    count = asyncio.run(_sweep_unfinalized_briefs_async())
    log.info("define_sweep_unfinalized_briefs_done", extra={"deleted": count})


async def _sweep_unfinalized_briefs_async() -> int:
    settings = get_settings()
    retention_days = int(settings.unfinalized_brief_retention_days)
    engine = make_worker_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with Session() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id FROM learning_briefs
                        WHERE finalized_at IS NULL
                          AND created_at < NOW() - make_interval(days => :days)
                        ORDER BY created_at
                        LIMIT :batch
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"days": retention_days, "batch": _BATCH},
                )
            ).fetchall()
            if not rows:
                return 0
            ids = [r.id for r in rows]
            await db.execute(
                text("DELETE FROM learning_briefs WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
            await db.commit()
            return len(ids)
    finally:
        with contextlib.suppress(Exception):
            await engine.dispose()
