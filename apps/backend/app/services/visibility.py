"""The single central authorizer — every visibility/discoverability predicate.

ADR-0026 §3 + ADR-0029 §D2 + DR-3-R2 / R-C1′ / DR-18-R2. This module is the
**only** non-lifecycle home for the four-column ``is_publicly_listed`` rule.
The CI grep-guard (``tests/test_no_raw_published_checks.py``) allow-lists the
status references here with the ``central authorizer`` marker; nothing else
outside the lifecycle state-machine may read ``status==published`` as an
access proxy.

Canonical predicate (R-C1′, supersedes the spec's ``IN (none, approved)``):

    is_publicly_listed(course) ==
        visibility == public
        AND status == published
        AND moderation_state == approved
        AND deleted_at IS NULL
        AND NOT quarantined        # DR-18-R2, wired in S2.10

``none``/``pending_review`` never list. The advisory classifier (S2.9) sets
queue priority only — it never auto-approves; ``approved`` requires an explicit
admin action (S6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, and_, or_, select

from app.models.course import Course, CourseStatus, Enrollment, ModerationState, Visibility

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.user import User


# ---------------------------------------------------------------------------
# quarantine accessor (DR-18-R2)
#
# ``courses.quarantined`` lands in migration 0044 (S2.10). Until then the
# column may be absent on a loaded row, so read it defensively so S2.3 stays
# self-contained — a missing column reads as ``False`` (not quarantined). The
# SQL forms add ``AND NOT quarantined`` in S2.10 once the column exists.
# ---------------------------------------------------------------------------


def _is_quarantined(course: Course) -> bool:
    return bool(getattr(course, "quarantined", False))


# ---------------------------------------------------------------------------
# Pure predicate (NFR-PERF-2 — no DB, no viewer)
# ---------------------------------------------------------------------------


def is_publicly_listed(course: Course) -> bool:
    """True iff the course is publicly discoverable (R-C1′ canonical predicate).

    A pure function over already-loaded columns. ``none`` is NOT listable;
    only ``approved`` lists. Soft-deleted and quarantined courses never list.
    """
    return (
        course.visibility == Visibility.public
        and course.status == CourseStatus.published  # noqa: published-check — central authorizer
        and course.moderation_state == ModerationState.approved
        and course.deleted_at is None
        and not _is_quarantined(course)
    )


def publicly_listed_sql() -> ColumnElement[bool]:
    """The SQL embodiment of :func:`is_publicly_listed` over the ``Course`` row.

    The **only** place the four-column AND is expressed for queries (catalog,
    search, subject counts, sitemap, MCP catalog, admin stats). Includes
    ``NOT quarantined`` (DR-18-R2 / S2.10) so a csam/illegal-quarantined course
    can never leak via any listing query — index-covered by ``ix_courses_listed``.
    """
    return and_(
        Course.visibility == Visibility.public,
        Course.status == CourseStatus.published,  # noqa: published-check — central authorizer
        Course.moderation_state == ModerationState.approved,
        Course.deleted_at.is_(None),
        Course.quarantined.is_(False),
    )


# ---------------------------------------------------------------------------
# Capability (R-CAP)
# ---------------------------------------------------------------------------


def can_publish_public(user: User) -> bool:
    """Capability check (ADR-0025 role-vs-capability): active + not suspended.

    Suspension (``is_active=False``) is the single revocation axis (R-CAP);
    quota + moderation are enforced at the call site / state machine.
    """
    return bool(getattr(user, "is_active", False))


def can_clone(course: Course, viewer: User | None = None) -> bool:
    """A course is clonable iff it is publicly listed (ADR-0027 consumes this).

    ``viewer`` is accepted for signature symmetry with the other predicates and
    future per-viewer rules; cloning today keys only on the source being listed.
    """
    return is_publicly_listed(course)


# ---------------------------------------------------------------------------
# Viewer-aware predicates (need the session for the grandfather enrollment read)
# ---------------------------------------------------------------------------


async def can_view_course(db: AsyncSession, course: Course, viewer: User | None) -> bool:
    """Authoritative course-detail visibility (ADR-0026 §3, replaces courses.py).

    True iff the course is publicly listed, OR the viewer is the owner, OR an
    admin, OR holds an Enrollment (grandfather, R-VIS-13) — **except** a
    quarantined (csam/illegal) course is invisible even to enrolled learners
    (full quarantine, R-C6′ / DR-18-R2).
    """
    if _is_quarantined(course):
        # Full quarantine: nobody — not even the owner or an enrolled learner.
        return False
    if is_publicly_listed(course):
        return True
    if viewer is None:
        return False
    if viewer.is_admin() or course.owner_id == viewer.id:
        return True
    from app.repositories import courses as courses_repo

    enrollment = await courses_repo.get_enrollment(db, user_id=viewer.id, course_id=course.id)
    if enrollment is None:
        return False
    # Grandfather (R-VIS-13): an enrolled learner keeps view after the course
    # goes private/unpublished — EXCEPT a hard-removed course. csam/illegal are
    # already handled by the quarantine short-circuit above; ``severe_abuse``
    # (and any non-quarantine hard-removal) soft-deletes the course and records
    # the reason, so the enrollment-grandfather branch is suppressed here while
    # the owner branch above keeps the owner's view/edit (FR-MOD-08 / S6.2).
    return not (course.deleted_at is not None and await _is_hard_removed(db, course))


async def _is_hard_removed(db: AsyncSession, course: Course) -> bool:
    """True iff the latest moderation event removed the course with a
    hard-removal reason (``severe_abuse``/csam/illegal). Only consulted for a
    soft-deleted course, so it costs at most one indexed event read on the cold
    removed-course path (never on the catalog hot path)."""
    from app.repositories import moderation as moderation_repo
    from app.services.moderation_taxonomy import HARD_REMOVAL_REASONS

    event = await moderation_repo.latest_event(db, course.id)
    if event is None or event.reason_code is None:
        return False
    return event.reason_code in {r.value for r in HARD_REMOVAL_REASONS}


async def can_learn_in_course(db: AsyncSession, course: Course, viewer: User | None) -> bool:
    """Can the viewer *learn* (open the tutor / lessons) in this course?

    Owner-bypass for self-learn on private/draft (FR-LEARN-01). Otherwise the
    same gate as :func:`can_view_course`. (The ``severe_abuse`` tutor-disable
    is a separate ``moderation_event.reason_code`` read — S6, not here.)
    """
    if _is_quarantined(course):
        return False
    if viewer is not None and course.owner_id == viewer.id:
        return True
    return await can_view_course(db, course, viewer)


async def can_enroll(
    db: AsyncSession, course: Course, viewer: User | None
) -> tuple[bool, str | None]:
    """``(True, None)`` for a listed course or the owner self-preview; else
    ``(False, "enrollment.not_available")``. Anonymous is handled by the caller
    (raises ``auth.required`` / 401).
    """
    if is_publicly_listed(course):
        return (True, None)
    if viewer is not None and course.owner_id == viewer.id:
        return (True, None)
    return (False, "enrollment.not_available")


# ---------------------------------------------------------------------------
# RAG / cross-course retrieval ACL (ADR-0029 §D2, R-S12)
# ---------------------------------------------------------------------------


def retrieval_acl_clause(requesting_user_id: str | None) -> ColumnElement[bool]:
    """SQL ACL over the already-joined ``Course`` row for RAG retrieval.

    ``is_publicly_listed OR (owner …) OR (enrolled …)`` — the SQL embodiment of
    :func:`can_view_course`'s grandfathering (R-VIS-13). The owner branch
    (R-S12) lets a user's own private/draft courses into *their* cross-course
    context; the enrollment branch lets a grandfathered learner keep retrieving
    a course they enrolled in before it went private/unpublished. Neither
    branch ever leaks another user's private course. A ``None`` requesting user
    (pure system context) collapses to the listed clause only.

    Quarantine is a full lockout (R-C6′ / DR-18-R2): a quarantined course is
    excluded from *every* branch — listed (via :func:`publicly_listed_sql`),
    owner, and enrolled — mirroring ``can_view_course`` which returns ``False``
    even for the owner or an enrolled learner. ``severe_abuse`` (the tutor-
    disable signal where the owner keeps view/edit) is a separate
    ``moderation_event`` read (S6) and, like ``can_view_course``, is not gated
    here.

    ``build_failed`` is an S3 ``CourseStatus`` value that may not exist yet —
    we reference it defensively as a string literal so the owner branch
    excludes the owner's failed drafts the moment S3 lands the enum value,
    without S2 importing a symbol that doesn't exist (R-S12 / PR-9 follow-up).

    The enrollment branch is an index-friendly correlated ``EXISTS`` keyed on
    ``enrollments(user_id, course_id)`` (the ``uq_enrollments_user_course``
    unique index), so it costs at most one index probe per candidate course.
    """
    listed = publicly_listed_sql()
    if requesting_user_id is None:
        return listed
    owner = and_(
        Course.owner_id == requesting_user_id,
        Course.deleted_at.is_(None),
        # String compare so this stays valid before S3's enum value exists; the
        # column is a String(20) so the literal compares correctly either way.
        Course.status != "build_failed",
        # DR-18-R2: a quarantined course never leaks even via the owner branch.
        Course.quarantined.is_(False),
    )
    # Grandfathered enrollment (R-VIS-13): the learner enrolled while the course
    # was visible and keeps retrieval access even after it goes private/
    # unpublished — but NEVER if it is quarantined (R-C6′ full lockout). Mirrors
    # ``can_view_course``'s ``get_enrollment is not None`` branch. Unlike the
    # ORM authorizer — whose callers 404 soft-deleted courses at the repo load,
    # a precondition this SQL path doesn't have — every SQL branch must carry
    # ``deleted_at IS NULL`` itself (the listed and owner branches already do;
    # soft-delete does NOT remove enrollment rows, so without the guard an
    # ex-enrollee could retrieve chunks of a deleted course).
    enrolled = and_(
        Course.quarantined.is_(False),
        Course.deleted_at.is_(None),
        select(Enrollment.id)
        .where(
            Enrollment.user_id == requesting_user_id,
            Enrollment.course_id == Course.id,
        )
        .exists(),
    )
    return or_(listed, owner, enrolled)
