"""Self-serve build wrapper (S3.7 / FR-DEFINE-13/15 / DR-1 / R-G1).

The thin durability/idempotency/quota shell around the self-critique authoring
orchestrator (:func:`authoring_orchestrator.draft_course`). It is the seam the
learner-facing ``POST /ai/courses/draft`` endpoint and the ``cancel-build`` /
sweep paths (S3.8/S3.10) build on:

* **Idempotent / re-runnable.** A finalized brief that already produced a live,
  non-``build_failed`` course replays that course (no second LLM run). A brief
  whose last build is ``build_failed`` is re-buildable: the new build flips a
  fresh course back to a clean ``draft`` (FR-DEFINE-15 — no manual deletion).
* **build_failed on unrecoverable failure (FR-DEFINE-15).** When the pipeline
  raises (``authoring.outliner_failed`` etc.) a ``status=build_failed`` private
  shell is committed in its own savepoint so the owner sees the failure (and can
  re-run) rather than a silent half-course or vendor error. The caller gets a
  NORMALIZED :class:`DefineBuildFailedError` — never the raw model output.
* **Non-dollar caps (FR-DEFINE-13 / DR-11).** A per-user advisory lock enforces
  the concurrency cap (default 1) + in-flight idempotency; a DB COUNT of recent
  ``course.built`` audit rows enforces the daily quota. Both are dollar-blind so
  a $0 BYOK build still counts. Quota is charged ONLY on a successful start.

The brief→course link (for replay + the S3.10 orphan sweep) is the ``brief_id``
recorded in the course's draft-trace payload — no new column / migration.
"""

from __future__ import annotations

import zlib

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    DefineBuildFailedError,
    DefineBuildInFlightError,
    DefineBuildQuotaError,
)
from app.models.audit import AuditEvent
from app.models.course import Course, CourseStatus, Visibility
from app.models.course_draft_trace import CourseDraftTrace
from app.models.user import User
from app.repositories import audit as audit_repo
from app.services import account as account_service
from app.services import authoring_orchestrator
from app.services.byok import PLATFORM_CONTEXT, LLMContext

log = structlog.get_logger(__name__)

#: Audit action a successful build START writes (the durable quota unit).
_BUILT_ACTION = "course.built"
#: Advisory-lock namespace (a stable arbitrary salt) so the build lock can't
#: collide with another feature's per-user advisory lock.
_LOCK_NAMESPACE = 0x5331  # "S1" — define/build namespace marker


def _user_lock_key(user_id: str) -> int:
    """Map a user id → a stable signed 64-bit advisory-lock key.

    ``pg_try_advisory_xact_lock(bigint)`` keys on a single 64-bit int; we hash the
    user id (CRC32, deterministic) into the low word and stamp the namespace into
    the high word so the build lock is disjoint from any other advisory lock.
    """
    low = zlib.crc32(user_id.encode("utf-8")) & 0xFFFFFFFF
    key = (_LOCK_NAMESPACE << 32) | low
    # Postgres advisory locks take a signed bigint; wrap into signed range.
    if key >= 2**63:
        key -= 2**64
    return key


async def _try_acquire_build_lock(db: AsyncSession, user_id: str) -> bool:
    """Try to take the per-user build advisory lock (xact-scoped).

    Returns True iff acquired. The lock auto-releases at transaction end (commit
    or rollback), so a crashed/aborted build never strands the lock — the next
    submit can proceed. ``define_build_concurrency`` is the conceptual cap; with a
    single xact-scoped try-lock the effective cap is 1 concurrent build per user,
    which is the default and the safe ceiling (a heavier cap would need a counter
    table — out of scope, the lock is the FR-DEFINE-13 backstop).
    """
    got = (
        await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _user_lock_key(user_id)}
        )
    ).scalar_one()
    return bool(got)


async def find_course_for_brief(db: AsyncSession, *, owner_id: str, brief_id: str) -> Course | None:
    """Most-recent live course this brief produced (replay + S3.10 sweep link).

    Resolves via the ``brief_id`` recorded in the course's draft-trace payload
    (set by both the success pipeline and the ``build_failed`` shell). Returns the
    course in ANY status (draft / build_failed / published) so the caller can tell
    a successful replay from a failed re-runnable shell. Soft-deleted courses are
    excluded.
    """
    stmt = (
        select(Course)
        .join(CourseDraftTrace, CourseDraftTrace.course_id == Course.id)
        .where(
            Course.owner_id == owner_id,
            Course.deleted_at.is_(None),
            CourseDraftTrace.payload["brief_id"].astext == brief_id,
        )
        .order_by(Course.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


async def _assert_build_quota(db: AsyncSession, user_id: str) -> None:
    """Daily build quota (non-dollar DB COUNT, FR-DEFINE-13). Raises 429 when over.

    Counts ``course.built`` audit rows by this user within the trailing window —
    durable (survives process restarts), dollar-blind. Charged only on a
    successful start, so a rejected (validation/replay) submit never consumes it.
    """
    s = get_settings()
    window_seconds = int(s.define_build_window_hours) * 3600
    used = (
        await db.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.actor_id == user_id,
                AuditEvent.action == _BUILT_ACTION,
                AuditEvent.created_at
                > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, window_seconds),
            )
        )
    ).scalar_one()
    if int(used or 0) >= int(s.define_build_quota_24h):
        raise DefineBuildQuotaError(
            "You've reached your course-build limit for now. Try again later.",
            details={
                "dimension": "builds",
                "used": int(used or 0),
                "limit": int(s.define_build_quota_24h),
            },
        )


async def _materialize_build_failed(db: AsyncSession, *, user: User, brief_id: str) -> None:
    """Commit a ``build_failed`` private shell linked to the brief (FR-DEFINE-15).

    Wrapped in a SAVEPOINT so it survives the failed pipeline's partial state
    rollback (the orchestrator commits its own course rows, but an outliner
    failure raises before any course exists — we create a minimal shell so the
    owner sees the failure and can re-run). If a course for this brief already
    exists (a prior failed shell), it is flipped to ``build_failed`` in place.
    """
    from app.services.courses import _unique_slug

    try:
        async with db.begin_nested():
            existing = await find_course_for_brief(db, owner_id=user.id, brief_id=brief_id)
            if existing is not None:
                existing.status = CourseStatus.build_failed
                existing.visibility = Visibility.private
                await db.flush()
                return
            # Fresh shell. Personal subject is the safe default (it always
            # resolves for a self-serve build; FR-DEFINE-12).
            from app.repositories import courses as courses_repo

            subject = await courses_repo.get_subject_by_slug(
                db, get_settings().personal_subject_slug
            )
            slug = await _unique_slug(db, "Untitled build")
            course = Course(
                owner_id=user.id,
                subject_id=subject.id if subject else None,
                title="Untitled build",
                slug=slug,
                overview="",
                status=CourseStatus.build_failed,
                visibility=Visibility.private,
            )
            db.add(course)
            await db.flush()
            # Link the shell to the brief via a trace row (the same channel the
            # success path + the S3.10 sweep read).
            db.add(
                CourseDraftTrace(
                    draft_id=f"failed_{course.id}",
                    course_id=course.id,
                    user_id=user.id,
                    step="outliner",
                    step_index=0,
                    payload={"brief_id": brief_id, "error": "build_failed"},
                    duration_ms=0,
                    status="error",
                )
            )
            await db.flush()
    except SQLAlchemyError:  # pragma: no cover — defensive, never block the re-raise
        log.exception("define_build_failed_shell_persist_failed", brief_id=brief_id)


async def build_from_brief(
    db: AsyncSession,
    *,
    user: User,
    brief_id: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> authoring_orchestrator.OrchestratorResult:
    """Run (or replay) a self-serve build for a finalized brief.

    Order: cooperative-cancel fence → in-flight advisory lock → replay
    short-circuit → daily quota → pipeline → audit ``course.built``. On pipeline
    failure: materialize a ``build_failed`` shell + raise a normalized error.
    Commits its own rows but not the outer transaction (caller's request commit).
    """
    # Fail-closed cooperative-cancel fence (R-S10): a suspended/deleted account
    # never starts a build.
    await account_service.assert_account_active(db, user.id)

    # In-flight idempotency + concurrency cap (FR-DEFINE-13). The xact-scoped
    # advisory lock means a concurrent build by the same user (same connection
    # can't, but a sibling request can) finds the lock held → 409.
    if not await _try_acquire_build_lock(db, user.id):
        raise DefineBuildInFlightError(
            "A course build is already running for your account. Please wait for it to finish."
        )

    # Replay short-circuit (idempotency): a live, non-failed course already built
    # from this brief is returned as-is — no second LLM run, no quota charge.
    existing = await find_course_for_brief(db, owner_id=user.id, brief_id=brief_id)
    if existing is not None and existing.status != CourseStatus.build_failed:
        return _result_for_existing(existing)

    # Validate + quota BEFORE charging anything. An un-finalized / unknown brief
    # raises inside draft_course (define.brief_not_finalized / session_not_found)
    # with no quota charge. We check finalization up front so the quota guard runs
    # only against a buildable brief (quota consumed only on a real start).
    await _assert_buildable(db, user=user, brief_id=brief_id)
    await _assert_build_quota(db, user.id)

    try:
        result = await authoring_orchestrator.draft_course(
            db, user=user, brief_id=brief_id, ctx=ctx
        )
    except DefineBuildFailedError:
        raise
    except AppError as exc:
        # Validation-class rejections (not_finalized / session_not_found /
        # subject_missing / access_revoked) propagate untouched — they are NOT a
        # build failure and must not mint a build_failed shell or charge quota.
        if exc.code in {
            "define.brief_not_finalized",
            "define.session_not_found",
            "define.personal_subject_missing",
            "account.access_revoked",
        }:
            raise
        # Genuine pipeline failure (e.g. authoring.outliner_failed): persist the
        # build_failed shell + surface a normalized, vendor-free error.
        await _materialize_build_failed(db, user=user, brief_id=brief_id)
        log.warning("define_build_failed", brief_id=brief_id, underlying=exc.code)
        raise DefineBuildFailedError(
            "We couldn't finish building your course. You can try again.",
            details={"brief_id": brief_id},
        ) from exc

    # Charge the quota unit on a successful start (FR-DEFINE-15).
    await audit_repo.record(
        db,
        actor_id=user.id,
        action=_BUILT_ACTION,
        target_type="course",
        target_id=result.course_id,
        data={"brief_id": brief_id, "draft_id": result.draft_id},
    )
    return result


async def _assert_buildable(db: AsyncSession, *, user: User, brief_id: str) -> None:
    """Pre-flight: the brief must exist (owner-scoped) AND be finalized.

    Mirrors the orchestrator's own checks but runs BEFORE the quota guard so a
    rejection never consumes quota. Raises the same 404/422 codes the orchestrator
    would, keeping the contract identical.
    """
    # Reuse the orchestrator's loader so the finalization + existence rules are
    # single-sourced (it raises define.brief_not_finalized / session_not_found).
    from app.core.errors import NotFoundError
    from app.repositories import learning_briefs as brief_repo

    brief_row = await brief_repo.get_active_session(db, session_id=brief_id, owner_id=user.id)
    if brief_row is None:
        raise NotFoundError("Goal session not found", code="define.session_not_found")
    # _load_build_brief raises define.brief_not_finalized when not finalized.
    authoring_orchestrator._load_build_brief(brief_row)


def _result_for_existing(course: Course) -> authoring_orchestrator.OrchestratorResult:
    """Shape an already-built course into an :class:`OrchestratorResult` for replay.

    The replay path does not re-run the critic, so the score fields are neutral —
    the client re-fetches the live trace via the trace endpoint for the real
    scores. ``module_count`` is read from the loaded relationship when present.
    """
    from app.services.authoring_orchestrator import CriticScores

    module_count = len(course.modules) if "modules" in course.__dict__ else 0
    return authoring_orchestrator.OrchestratorResult(
        course_id=course.id,
        slug=course.slug,
        module_count=module_count,
        lesson_count=0,
        final_score=CriticScores(coverage=0, learning_arc=0, scope=0),
        final_rationale="(replayed — see the draft trace for the build's scores)",
        draft_id="",
        revisions_used=0,
    )
