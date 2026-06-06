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
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    DefineBuildFailedError,
    DefineBuildInFlightError,
    DefineBuildQuotaError,
)
from app.db.base import get_sessionmaker
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
    (set by the shell-first materialization, the success pipeline, and the
    ``build_failed`` shell). Returns the course in ANY status (draft /
    build_failed / published) so the caller can tell a successful replay from a
    failed re-runnable shell from an in-flight empty shell.
    :func:`_is_successfully_built` distinguishes a completed build (``build_
    completed_at`` stamped) from an in-flight/crashed/cancelled shell via that
    column (migration 0052), NOT the old ">=1 module" heuristic. ``modules`` stay
    eager-loaded for :func:`_result_for_existing`'s ``module_count``. Soft-deleted
    courses are excluded.
    """
    stmt = (
        select(Course)
        .join(CourseDraftTrace, CourseDraftTrace.course_id == Course.id)
        .where(
            Course.owner_id == owner_id,
            Course.deleted_at.is_(None),
            CourseDraftTrace.payload["brief_id"].astext == brief_id,
        )
        .options(selectinload(Course.modules))
        .order_by(Course.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


def _is_successfully_built(course: Course) -> bool:
    """True iff ``course`` is a completed, replayable build (not a shell).

    A successful build is a course whose status is NOT ``build_failed`` AND whose
    ``build_completed_at`` is stamped (the honest completion marker, migration
    0052). This REPLACES the old fragile ">=1 module" heuristic (Codex confirm-
    round P1): the shell-first build now commits PER-PHASE — the outline phase
    (parent-row title/overview/etc + skeleton modules/lessons) commits BEFORE the
    lesson-drafting loop so the parent-row write lock is released and a concurrent
    cancel/failure-flip is never blocked. That makes ">=1 module" a LIE: a build
    that crashed mid-loop (process death before the failure handler flips it to
    ``build_failed``) HAS modules but is NOT a completed build. ``build_completed_at
    IS NOT NULL`` is stamped only at the very end of a successful pipeline, so a
    crashed/cancelled mid-build draft (NULL) is correctly re-buildable — exactly
    like ``build_failed`` — instead of being replayed as a (partial) success.
    """
    if course.status == CourseStatus.build_failed:
        return False
    return course.build_completed_at is not None


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


async def _materialize_build_shell(*, user: User, brief_id: str) -> str:
    """Commit an in-flight course shell linked to the brief, in its OWN session.

    The shell is the durable spine the whole build hangs on (Codex P1 + Gate-B
    F1). It is created and **committed in a fresh session from
    :func:`get_sessionmaker`** — independent of the request session — so it
    survives the request's commit-or-rollback regardless of how the pipeline ends.
    That closes two holes at once:

    * **Codex P1.** The old design materialized the ``build_failed`` row inside
      the request session via a SAVEPOINT and only on failure; ``get_db`` rolls
      the whole session back on exception, so the shell never persisted on the
      outliner/lesson failure path — killing the retry/idempotency/sweep
      contracts on exactly their target path.
    * **Gate-B F1.** The cancel button + status poll need a ``course_id`` while
      ``phase==='building'``; the synchronous build endpoint only returns it at
      the END. A committed shell gives the UI a row to poll (via
      ``GET /me/briefs/{id}/course``) and a target to cancel mid-build.

    **State adjudication (S3.7 / ADR-0029).** The shell starts ``status=draft``,
    NOT ``build_failed``: the IMPLEMENTATION-PLAN S3.7 spec + ADR-0029 D2 enumerate
    only ``draft/published/archived/build_failed`` — no dedicated ``building``
    state was specified, and adding one is out of scope ("no DDL/migration").
    ``build_failed`` is wrong for the in-flight shell because the replay short-
    circuit treats it as retryable AND ``retrieval_acl_clause`` excludes it from
    the owner's own RAG. A mid-build empty ``draft`` is owner-visible but has zero
    chunks (never indexed), so it leaks nothing; the brief-link trace row is the
    marker the cancel endpoint, the sweep, and the replay distinguisher
    (:func:`_is_successfully_built`) recognise. On a re-run of a prior
    ``build_failed`` course this flips that SAME course back to ``draft`` and
    reuses it (FR-DEFINE-15 — no manual deletion, no duplicate row).

    Returns the shell's ``course_id``.
    """
    from app.repositories import courses as courses_repo
    from app.services.courses import _unique_slug

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as shell_db:
        existing = await find_course_for_brief(shell_db, owner_id=user.id, brief_id=brief_id)
        if existing is not None:
            # Re-run of a failed/abandoned shell: reuse it, reset to a clean
            # in-flight draft (FR-DEFINE-15). Its modules are dropped by the
            # pipeline's overwrite of the same row.
            existing.status = CourseStatus.draft
            existing.visibility = Visibility.private
            await shell_db.commit()
            return existing.id
        # Fresh shell. Personal subject is the safe default (it always resolves
        # for a self-serve build; FR-DEFINE-12).
        subject = await courses_repo.get_subject_by_slug(
            shell_db, get_settings().personal_subject_slug
        )
        slug = await _unique_slug(shell_db, "Untitled build")
        course = Course(
            owner_id=user.id,
            subject_id=subject.id if subject else None,
            title="Untitled build",
            slug=slug,
            overview="",
            status=CourseStatus.draft,
            visibility=Visibility.private,
        )
        shell_db.add(course)
        await shell_db.flush()
        # Link the shell to the brief via a trace row (the same channel the
        # success path, the cancel endpoint, and the S3.10 sweep read).
        shell_db.add(
            CourseDraftTrace(
                draft_id=f"shell_{course.id}",
                course_id=course.id,
                user_id=user.id,
                step="outliner",
                step_index=0,
                payload={"brief_id": brief_id, "phase": "building"},
                duration_ms=0,
                status="ok",
            )
        )
        await shell_db.commit()
        return course.id


async def _flip_shell_to_build_failed(*, course_id: str) -> None:
    """Flip the committed shell to ``build_failed`` in its OWN session (FR-DEFINE-15).

    Runs in a fresh session from :func:`get_sessionmaker` so it is immune to the
    request session's rollback: when the pipeline raises, ``get_db`` rolls back
    the request session (discarding the half-built tree), but this UPDATE has
    already committed the terminal ``build_failed`` state on the durable shell. A
    course the owner cancelled mid-build is already ``build_failed`` — the
    ``WHERE status != build_failed`` guard keeps this idempotent and avoids
    clobbering the cancel's audit trail.

    Codex confirm-round P1 guard: also require ``build_completed_at IS NULL``.
    Now that the build commits per-phase (the success path stamps
    ``build_completed_at`` + commits the final tree on the request session BEFORE
    this failure handler could fire), a flip must NEVER demote a course that
    actually finished between a late non-fatal error and this flip — only an
    unfinished (NULL) shell is a real failure.
    """
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as fail_db:
            await fail_db.execute(
                text(
                    "UPDATE courses SET status = 'build_failed', visibility = 'private', "
                    "is_featured = false "
                    "WHERE id = :id AND deleted_at IS NULL AND status != 'build_failed' "
                    "AND build_completed_at IS NULL"
                ),
                {"id": course_id},
            )
            await fail_db.commit()
    except SQLAlchemyError:  # pragma: no cover — defensive, never block the re-raise
        log.exception("define_build_failed_shell_flip_failed", course_id=course_id)


async def build_from_brief(
    db: AsyncSession,
    *,
    user: User,
    brief_id: str,
    ctx: LLMContext = PLATFORM_CONTEXT,
) -> authoring_orchestrator.OrchestratorResult:
    """Run (or replay) a self-serve build for a finalized brief.

    Order: cooperative-cancel fence → in-flight advisory lock → replay
    short-circuit → daily quota → **shell-first materialize** → pipeline →
    audit ``course.built``. The shell is committed in its OWN session BEFORE the
    pipeline runs (Codex P1 + Gate-B F1) so a mid-build failure or crash leaves a
    durable row the retry/sweep/cancel paths recognise, and so the UI has a
    ``course_id`` to poll + cancel while the synchronous build is still running.
    On pipeline failure: flip the committed shell to ``build_failed`` (own
    session, rollback-immune) + raise a normalized error. On success: the request
    txn commits the full tree the pipeline wrote INTO the shell row.

    Commits the shell + the failure-flip in their own sessions; the success tree +
    the audit ride the caller's request commit (same pattern as the orchestrator).
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

    # Replay short-circuit (idempotency): a live, SUCCESSFULLY-BUILT course
    # already produced by this brief is returned as-is — no second LLM run, no
    # quota charge. A ``build_failed`` shell OR an empty (mid-build/crashed)
    # ``draft`` shell is NOT a successful build and falls through to a re-run
    # (FR-DEFINE-15 re-runnable; invariant 2 — an empty shell never replays as
    # success).
    existing = await find_course_for_brief(db, owner_id=user.id, brief_id=brief_id)
    if existing is not None and _is_successfully_built(existing):
        return _result_for_existing(existing)

    # Validate + quota BEFORE charging anything. An un-finalized / unknown brief
    # raises inside draft_course (define.brief_not_finalized / session_not_found)
    # with no quota charge. We check finalization up front so the quota guard runs
    # only against a buildable brief (quota consumed only on a real start).
    await _assert_buildable(db, user=user, brief_id=brief_id)
    await _assert_build_quota(db, user.id)

    # Shell-first: commit the durable in-flight shell in its own session BEFORE
    # the pipeline starts. The pipeline then FILLS this exact row (so success =
    # one course, not two) and a failure flips this same row to build_failed.
    shell_course_id = await _materialize_build_shell(user=user, brief_id=brief_id)

    try:
        result = await authoring_orchestrator.draft_course(
            db, user=user, brief_id=brief_id, ctx=ctx, existing_course_id=shell_course_id
        )
    except DefineBuildFailedError:
        raise
    except AppError as exc:
        # Validation-class rejections (not_finalized / session_not_found /
        # subject_missing / access_revoked) propagate untouched — they are NOT a
        # build failure and must not flip the shell to build_failed or charge
        # quota. (assert_account_active already ran, but a mid-run suspension can
        # still surface account.access_revoked here.)
        if exc.code in {
            "define.brief_not_finalized",
            "define.session_not_found",
            "define.personal_subject_missing",
            "account.access_revoked",
        }:
            raise
        # Genuine pipeline failure (e.g. authoring.outliner_failed): flip the
        # committed shell to build_failed (rollback-immune) + surface a
        # normalized, vendor-free error.
        await _flip_shell_to_build_failed(course_id=shell_course_id)
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


async def brief_course_status(
    db: AsyncSession, *, owner_id: str, brief_id: str
) -> tuple[str, str] | None:
    """Owner-scoped ``(course_id, status)`` for the brief's in-flight/built course.

    Backs ``GET /me/briefs/{brief_id}/course`` (Gate-B F1): while the synchronous
    build endpoint hasn't returned yet, the UI polls this to obtain the cancel
    target (``course_id``) and detect terminal states (``draft`` = built/in-flight,
    ``build_failed`` = failed/cancelled). Resolves through :func:`find_course_for_brief`
    so it returns the SAME shell the build threads. Returns ``None`` when no shell
    exists yet (the build hasn't materialized one) so the caller 404s — which the
    UI treats as "still spinning up."
    """
    course = await find_course_for_brief(db, owner_id=owner_id, brief_id=brief_id)
    if course is None:
        return None
    return course.id, str(course.status)
