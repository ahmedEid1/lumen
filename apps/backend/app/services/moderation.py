"""Admin-authority moderation transitions (ADR-0026 §4 / S6.2).

S2 ships the **owner-intent** transitions (publish/unpublish/share/unshare/
resubmit) in ``app/services/courses.py``. This module owns the **admin-
authority** transitions — ``approve / reject / delist / relist / remove_course``
— the only path that sets ``moderation_state == approved`` (which is what makes
the visibility flag-flip meaningful) and the only path that quarantines or
hard-removes a course.

Each transition:

* validates the legal source state (else ``ValidationAppError`` /
  ``ConflictError``);
* writes a ``ModerationEvent`` (durable history) **and** an ``AuditEvent``
  (``admin.course.*``, with ip/ua threaded from the endpoint);
* sets ``courses.quarantined`` for ``csam``/``illegal`` hard-removal
  (DR-18-R2 — the single source of truth for the full-quarantine path);
* best-effort bumps the catalog cache version + enqueues the public RAG
  reindex on transition-to-listed (swallows broker errors, CLAUDE.md).

Revocation on hard-removal is enforced at the **authorizer**, not by deleting
enrollment rows: csam/illegal sets ``quarantined`` (``can_view_course`` returns
False for everyone incl. owner); ``severe_abuse`` soft-deletes + records the
reason, and ``can_view_course`` suppresses the enrollment-grandfather branch for
a removed course while keeping the owner's view/edit (FR-MOD-08).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.models.course import Course, ModerationState, Visibility
from app.repositories import audit as audit_repo
from app.repositories import courses as courses_repo
from app.repositories import moderation as moderation_repo
from app.services import courses as courses_service
from app.services import visibility as visibility_service
from app.services.moderation_taxonomy import (
    QUARANTINE_REASONS,
    ReasonCode,
    sanitize_note,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.moderation import CourseReport
    from app.models.user import User


async def _load_course(db: AsyncSession, course_id: str) -> Course:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    return course


async def _record(
    db: AsyncSession,
    *,
    course: Course,
    actor: User,
    action: str,
    from_state: str,
    to_state: str,
    reason: ReasonCode | None,
    note: str | None,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Write the paired ModerationEvent + AuditEvent for a transition."""
    clean_note = sanitize_note(note)
    await moderation_repo.record_event(
        db,
        course_id=course.id,
        actor_id=actor.id,
        from_state=from_state,
        to_state=to_state,
        reason_code=reason.value if reason else None,
        note=clean_note,
    )
    data: dict = {}
    if reason is not None:
        data["reason"] = reason.value
    if clean_note is not None:
        data["note"] = clean_note
    await audit_repo.record(
        db,
        actor_id=actor.id,
        action=action,
        target_type="course",
        target_id=course.id,
        ip_address=ip,
        user_agent=user_agent,
        data=data,
    )


async def approve_course(
    db: AsyncSession,
    *,
    course_id: str,
    actor: User,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Course:
    """Admin approves a pending_review course → ``approved`` (lists it).

    Legal source: ``pending_review`` (FR-MOD-01). Bumps the catalog cache and
    enqueues the public RAG reindex (transition-to-listed, FR-VIS-17).
    """
    course = await _load_course(db, course_id)
    if course.moderation_state != ModerationState.pending_review:
        raise ValidationAppError(
            f"Cannot approve from {course.moderation_state}",
            code="course.invalid_transition",
        )
    from_state = str(course.moderation_state)
    course.moderation_state = ModerationState.approved
    await _record(
        db,
        course=course,
        actor=actor,
        action="admin.course.approve",
        from_state=from_state,
        to_state=str(ModerationState.approved),
        reason=None,
        note=note,
        ip=ip,
        user_agent=user_agent,
    )
    await courses_service._bump_catalog_cache_version()
    courses_service._schedule_embedding_index(course.id)
    return course


async def reject_course(
    db: AsyncSession,
    *,
    course_id: str,
    actor: User,
    reason: ReasonCode | None = None,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Course:
    """Admin rejects a pending_review course → ``rejected`` + force-private
    (FR-MOD-07). moderation_state stays sticky thereafter (R-C2)."""
    course = await _load_course(db, course_id)
    if course.moderation_state != ModerationState.pending_review:
        raise ValidationAppError(
            f"Cannot reject from {course.moderation_state}",
            code="course.invalid_transition",
        )
    from_state = str(course.moderation_state)
    course.moderation_state = ModerationState.rejected
    course.visibility = Visibility.private
    course.is_featured = False
    await _record(
        db,
        course=course,
        actor=actor,
        action="admin.course.reject",
        from_state=from_state,
        to_state=str(ModerationState.rejected),
        reason=reason,
        note=note,
        ip=ip,
        user_agent=user_agent,
    )
    await courses_service._bump_catalog_cache_version()
    return course


async def delist_course(
    db: AsyncSession,
    *,
    course_id: str,
    actor: User,
    reason: ReasonCode | None = None,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Course:
    """Admin delists an approved course → ``delisted`` + de-feature (FR-MOD-03).

    NOT soft-deleted — the owner keeps their content; only public listing is
    pulled. **Idempotent**: a second delist on an already-delisted course is a
    no-op (no new event), so report-resolution double-fires don't spam history.
    """
    course = await _load_course(db, course_id)
    if course.moderation_state == ModerationState.delisted:
        # Idempotent — already delisted, write nothing.
        return course
    from_state = str(course.moderation_state)
    course.moderation_state = ModerationState.delisted
    course.is_featured = False
    await _record(
        db,
        course=course,
        actor=actor,
        action="admin.course.delist",
        from_state=from_state,
        to_state=str(ModerationState.delisted),
        reason=reason,
        note=note,
        ip=ip,
        user_agent=user_agent,
    )
    await courses_service._bump_catalog_cache_version()
    return course


async def relist_course(
    db: AsyncSession,
    *,
    course_id: str,
    actor: User,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Course:
    """Admin relists a delisted course → ``approved`` (FR-MOD-04).

    Only succeeds if the predicate *would* hold once approved — i.e. the course
    is still public + published + live + not quarantined. Otherwise raises
    ``ConflictError(course.not_listable)`` (e.g. the owner unshared/unpublished
    it after the delist).
    """
    course = await _load_course(db, course_id)
    if course.moderation_state != ModerationState.delisted:
        raise ValidationAppError(
            f"Cannot relist from {course.moderation_state}",
            code="course.invalid_transition",
        )
    # Would approving make it listable? Check every non-moderation_state column
    # of the predicate (visibility/status/deleted_at/quarantined).
    course.moderation_state = ModerationState.approved
    if not visibility_service.is_publicly_listed(course):
        # Roll the in-memory change back and refuse.
        course.moderation_state = ModerationState.delisted
        raise ConflictError(
            "Course is not currently listable (owner unshared/unpublished it)",
            code="course.not_listable",
        )
    await _record(
        db,
        course=course,
        actor=actor,
        action="admin.course.relist",
        from_state=str(ModerationState.delisted),
        to_state=str(ModerationState.approved),
        reason=None,
        note=note,
        ip=ip,
        user_agent=user_agent,
    )
    await courses_service._bump_catalog_cache_version()
    courses_service._schedule_embedding_index(course.id)
    return course


async def remove_course(
    db: AsyncSession,
    *,
    course_id: str,
    actor: User,
    reason: ReasonCode,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Course:
    """Admin hard-removes a course (soft-delete + revoke enrolled access).

    ``reason ∈ {csam, illegal}`` → ``quarantined = True`` (full lockout: even
    the owner and enrolled learners lose view, R-C6′ / DR-18-R2).
    ``severe_abuse`` → ``quarantined`` stays False; the course is soft-deleted
    and the latest event records ``severe_abuse`` so the authorizer suppresses
    the enrollment-grandfather branch while the owner keeps view/edit
    (FR-MOD-08). Any taxonomy reason is accepted; only the quarantine set
    flips the column.

    The transition is itself idempotent on the soft-delete: re-removing an
    already-deleted course still records the (possibly stronger) reason but does
    not change ``deleted_at`` if already set.
    """
    course = await _load_course(db, course_id)
    from_state = str(course.moderation_state)
    if course.deleted_at is None:
        course.deleted_at = datetime.now(UTC)
    course.is_featured = False
    if reason in QUARANTINE_REASONS:
        course.quarantined = True
    await _record(
        db,
        course=course,
        actor=actor,
        action="admin.course.remove",
        from_state=from_state,
        # remove does not change moderation_state itself (it is sticky); the
        # event records the removal with deleted_at + quarantined as the effect.
        to_state=str(course.moderation_state),
        reason=reason,
        note=note,
        ip=ip,
        user_agent=user_agent,
    )
    await courses_service._bump_catalog_cache_version()
    return course


# ---------------------------------------------------------------------------
# User-filed reports (S6.3 / DR-20)
# ---------------------------------------------------------------------------


def _reporter_is_eligible(reporter: User) -> bool:
    """DR-20 reporter eligibility: email-verified AND account-age ≥ threshold.

    The anti-brigading control — a throwaway account can't mass-report. Layered
    on top of the per-user ≤10/h ``@limiter`` cap and the per-course window cap.
    """
    if getattr(reporter, "email_verified_at", None) is None:
        return False
    created_at = getattr(reporter, "created_at", None)
    if created_at is None:
        return False
    threshold = timedelta(days=get_settings().report_min_account_age_days)
    return datetime.now(UTC) - created_at >= threshold


async def report_course(
    db: AsyncSession,
    *,
    course: Course,
    reporter: User,
    reason: ReasonCode,
    note: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> CourseReport:
    """File (or coalesce) a user report against a publicly-listed course.

    Preconditions enforced (in order, so the existence-hide 404 wins):

    * the course must be **publicly listed** — else ``NotFoundError`` (existence-
      hide, FR-MOD-11; reportability routes through ``is_publicly_listed``, never
      a raw status check);
    * the reporter must not be the owner — else ``ValidationAppError
      (report.own_course)``;
    * the reporter must be DR-20-eligible (verified + aged) — else
      ``ForbiddenError(report.ineligible)``;
    * the per-course rolling-window cap must not be exceeded — else
      ``RateLimitedError(course.report_rate_limited)``.

    On success: coalesces onto the reporter's existing OPEN report (updating its
    reason/note) or inserts a new open row, runs ``note`` through
    ``sanitize_note`` (FR-MOD-13), and writes a ``course.report`` audit
    (actor=reporter, ip/ua).
    """
    if not visibility_service.is_publicly_listed(course):
        # Existence-hide: a non-listed course is indistinguishable from a
        # missing one to a non-owner (FR-MOD-11 / R-U1).
        raise NotFoundError("Course not found", code="course.not_found")
    if course.owner_id == reporter.id:
        raise ValidationAppError("You cannot report your own course", code="report.own_course")
    if not _reporter_is_eligible(reporter):
        raise ForbiddenError(
            "Your account is not yet eligible to file reports",
            code="report.ineligible",
        )

    settings = get_settings()
    clean_note = sanitize_note(note)

    existing = await moderation_repo.get_open_report(
        db, course_id=course.id, reporter_id=reporter.id
    )
    if existing is not None:
        # Coalesce: update the reporter's open report rather than insert a
        # duplicate (partial-unique backstop). This does NOT count against the
        # per-course window — it is the same report being amended.
        existing.reason = reason.value
        existing.note = clean_note
        await db.flush()
        report = existing
    else:
        # Per-course brigading cap (DR-20) — only NEW reports count.
        window_start = datetime.now(UTC) - timedelta(hours=settings.report_per_course_window_hours)
        recent = await moderation_repo.count_reports_in_window(
            db, course_id=course.id, since=window_start
        )
        if recent >= settings.report_per_course_window_max:
            raise RateLimitedError(
                "This course has received too many reports recently",
                code="course.report_rate_limited",
            )
        report = await moderation_repo.create_report(
            db,
            course_id=course.id,
            reporter_id=reporter.id,
            reason=reason.value,
            note=clean_note,
        )

    await audit_repo.record(
        db,
        actor_id=reporter.id,
        action="course.report",
        target_type="course",
        target_id=course.id,
        ip_address=ip,
        user_agent=user_agent,
        data={"reason": reason.value},
    )
    return report
