"""Course/module/lesson orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    CloneCourseLimitError,
    CloneRateLimitedError,
    CloneSourceChangedError,
    CloneSourceNotClonableError,
    CloneSourceTooLargeError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.course import (
    Course,
    CourseStatus,
    Lesson,
    LessonType,
    ModerationState,
    Module,
    Visibility,
)
from app.models.moderation import ModerationEvent
from app.models.notification import NotificationKind
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import courses as courses_repo
from app.repositories import notifications as notifications_repo
from app.services import clone_projection, moderation_safety
from app.services import idempotency as idempotency_service
from app.services import visibility as visibility_service

# Re-export the central authorizer's can_view_course (ADR-0026 §3 / S2.4) so
# existing callers of ``courses.can_view_course`` are unchanged.
from app.services.visibility import can_view_course

log = get_logger(__name__)

__all__ = ["can_view_course"]

if TYPE_CHECKING:
    from app.schemas.course import (
        CourseCreate,
        CourseUpdate,
        LessonCreate,
        LessonUpdate,
        ModuleCreate,
        ModuleUpdate,
    )


def _validate_complete_order(mapping: dict[str, int], *, present_ids: set[str], kind: str) -> None:
    """Reject reorder payloads that would leave rows in an inconsistent state.

    Both reorder paths set every row's order to a negative temp value to
    side-step the unique constraint, then assign the new orders. A
    *partial* mapping leaves the unmentioned rows stuck at the temp value
    (so they appear *first* in the syllabus on next render — a silent
    rearrangement). Duplicate target values would crash the unique
    constraint at flush; negative targets would do the same on the next
    reorder. Catch all three up front with explicit error codes.
    """
    mapping_ids = set(mapping.keys())
    if mapping_ids != present_ids:
        missing = sorted(present_ids - mapping_ids)
        unknown = sorted(mapping_ids - present_ids)
        raise ValidationAppError(
            f"Reorder must cover every {kind[:-1]} exactly once",
            code=f"{kind}.partial_order",
            details={"missing": missing, "unknown": unknown},
        )
    values = list(mapping.values())
    if any(v < 0 for v in values):
        raise ValidationAppError(
            "Order values must be non-negative",
            code=f"{kind}.negative_order",
        )
    if len(set(values)) != len(values):
        raise ValidationAppError(
            "Order values must be unique",
            code=f"{kind}.duplicate_order",
        )


# ---------- Course ----------


async def create_course(db: AsyncSession, owner: User, payload: CourseCreate) -> Course:
    # S1.5 / FR-RBAC-04: course creation is ungated from the instructor role —
    # any active user may author (the route's `RequireAuthor` capability dep
    # already rejects anonymous/suspended callers; ownership of *edits* stays
    # enforced via `_can_edit_course`). The old `courses.forbidden` business
    # gate is removed (ADR-0025 §D4); no code path raises it anymore.
    subject = await courses_repo.get_subject(db, payload.subject_id)
    if not subject:
        raise NotFoundError("Subject not found", code="subject.not_found")

    slug = await _unique_slug(db, payload.title)
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=payload.title,
        slug=slug,
        overview=payload.overview,
        difficulty=payload.difficulty,
        cover_url=payload.cover_url,
        learning_outcomes=list(payload.learning_outcomes),
    )
    if payload.tag_ids:
        course.tags = await courses_repo.list_tags_by_ids(db, payload.tag_ids)
    db.add(course)
    await _flush_course_with_slug_retry(db, course, title=payload.title)
    return course


async def update_course(
    db: AsyncSession, *, course_id: str, owner: User, payload: CourseUpdate
) -> Course:
    course = await _owned_course(db, course_id, owner)
    title_changed = False
    if payload.title is not None and payload.title != course.title:
        course.title = payload.title
        course.slug = await _unique_slug(db, payload.title, exclude_id=course.id)
        title_changed = True
    if payload.subject_id is not None and payload.subject_id != course.subject_id:
        subject = await courses_repo.get_subject(db, payload.subject_id)
        if not subject:
            raise NotFoundError("Subject not found", code="subject.not_found")
        course.subject_id = subject.id
    for field in ("overview", "difficulty", "cover_url"):
        value = getattr(payload, field)
        if value is not None:
            setattr(course, field, value)
    if payload.tag_ids is not None:
        course.tags = await courses_repo.list_tags_by_ids(db, payload.tag_ids)
    if payload.learning_outcomes is not None:
        course.learning_outcomes = list(payload.learning_outcomes)
    # S2.11 / FR-VIS-08: PATCH no longer transitions status. Lifecycle moved to
    # the explicit publish/unpublish endpoints; ``status`` was dropped from
    # CourseUpdate (extra="forbid" rejects it).
    # When the title changed we minted a new slug via _unique_slug, but
    # that check is racy — a concurrent rename could have just claimed
    # the same candidate. Flush the slug update inside a savepoint with
    # the same retry helper the create/duplicate paths use, otherwise
    # the collision would surface as an unhandled IntegrityError when
    # the request-end commit fires.
    if title_changed:
        await _flush_course_with_slug_retry(db, course, title=course.title)
    return course


async def delete_course(db: AsyncSession, *, course_id: str, owner: User) -> None:
    course = await _owned_course(db, course_id, owner)
    course.deleted_at = datetime.now(UTC)


_VALID_STATUS_TRANSITIONS: dict[CourseStatus, set[CourseStatus]] = {
    CourseStatus.draft: {CourseStatus.published, CourseStatus.archived},  # noqa: published-check — state-machine write
    CourseStatus.published: {CourseStatus.draft, CourseStatus.archived},  # noqa: published-check — state-machine write
    CourseStatus.archived: {CourseStatus.draft},
}


async def _transition_status(db: AsyncSession, course: Course, target: CourseStatus) -> None:
    if course.status == target:
        return
    if target not in _VALID_STATUS_TRANSITIONS[course.status]:
        raise ValidationAppError(
            f"Invalid transition {course.status} → {target}", code="course.invalid_transition"
        )
    if target == CourseStatus.published:  # noqa: published-check — state-machine write
        if not course.title or not course.overview:
            raise ValidationAppError(
                "Course must have a title and overview to publish", code="course.missing_fields"
            )
        # Refuse to publish a course with zero live lessons. Students who
        # enrolled in an empty course would land on a blank syllabus with
        # nothing to mark complete — progress is stuck at 0% forever
        # (count_completed/count_lessons with total=0 returns 0.0), and
        # they have no signal that the course is unfinished by the author.
        lesson_count = await courses_repo.count_lessons_in_course(db, course.id)
        if lesson_count == 0:
            raise ValidationAppError(
                "Add at least one lesson before publishing",
                code="course.no_lessons",
            )
        course.published_at = datetime.now(UTC)
    course.status = target
    if target in (CourseStatus.draft, CourseStatus.archived):
        # Force-private side-effects on unpublish/archive (ADR-0026 §4): a
        # course can only be public while published, so leaving published
        # atomically drops it private + unfeatures it. moderation_state is
        # left UNTOUCHED — it is sticky (R-C2), so a previously-approved or
        # rejected course keeps that history for R-M9 re-approval.
        course.visibility = Visibility.private
        course.is_featured = False
    if target == CourseStatus.published:  # noqa: published-check — state-machine write
        _schedule_embedding_index(course.id)


def _schedule_embedding_index(course_id: str) -> None:
    """Best-effort enqueue of the embedding-index task on publish.

    Phase E0 wires every publish/re-publish through Celery so the
    course's lesson chunks land in ``lesson_chunks`` before the
    learner has a chance to ask the tutor anything. The send is
    best-effort by design: if the broker is unreachable (the dev
    stack ships without a worker by default, and Redis can blip in
    prod), we log a warning and move on. The same defensive shape
    that A9 removed when search was reindex-on-publish — we never
    let a downstream subsystem block a successful publish.
    """
    try:
        # Deferred import so importing this module from a context
        # without Celery installed (alembic, migrations CLI, etc.)
        # still works.
        from app.workers.tasks.embeddings import index_course_embeddings

        index_course_embeddings.delay(course_id)
    except Exception:  # pragma: no cover — broker may be down
        log.warning("embedding_index_enqueue_failed", course_id=course_id)


# Redis key holding a monotonically-increasing catalog cache version. Every
# transition that can change what is publicly listed bumps it; the catalog
# response cache keys off it so a share/approve/delist invalidates in O(1)
# without a per-row purge (ADR-0026 §"Consequences"; the Caddy surrogate-key
# path is unconfirmed, so this version bump is the durable fallback).
_CATALOG_CACHE_VERSION_KEY = "catalog:cache_version"


async def _bump_catalog_cache_version() -> None:
    """Best-effort O(1) catalog-cache invalidation (ADR-0026).

    Swallows broker errors like the embedding enqueue (Celery/Redis is
    best-effort in dev) so a moderation/lifecycle transition never fails
    because Redis blipped.
    """
    try:
        import redis.asyncio as redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            await client.incr(_CATALOG_CACHE_VERSION_KEY)
        finally:
            await client.aclose()
    except Exception:  # pragma: no cover — Redis may be down
        log.warning("catalog_cache_version_bump_failed")


# ---------- Owner-intent lifecycle + share (ADR-0026 §4; S2.9) ----------
#
# S2 ships the OWNER-INTENT transitions: publish / unpublish (lifecycle) and
# share / unshare / resubmit (sharing). The ADMIN-AUTHORITY transitions
# (approve / reject / delist / relist / remove) are S6's — they are the only
# way ``approved`` is set, which is what makes the flag-flip rollout meaningful.


async def _write_moderation_event(
    db: AsyncSession,
    *,
    course: Course,
    actor_id: str | None,
    from_state: str | None,
    to_state: str,
    reason_code: str | None = None,
    note: str | None = None,
    classifier_signal: dict | None = None,
) -> ModerationEvent:
    event = ModerationEvent(
        course_id=course.id,
        actor_id=actor_id,
        from_state=from_state,
        to_state=to_state,
        reason_code=reason_code,
        note=note,
        classifier_signal=classifier_signal,
    )
    db.add(event)
    await db.flush()
    return event


async def publish_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner publishes a draft course (draft→published). Visibility unchanged
    (stays private — published-private self-learn). Audits ``course.publish``."""
    course = await _owned_course(db, course_id, owner)
    await _transition_status(db, course, CourseStatus.published)  # noqa: published-check — state-machine write
    await audit_repo.record(
        db, actor_id=owner.id, action="course.publish", target_type="course", target_id=course.id
    )
    return course


async def unpublish_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner unpublishes (published→draft). Atomic force-private + unfeature;
    moderation_state stays sticky. Audits ``course.unpublish``."""
    course = await _owned_course(db, course_id, owner)
    was_featured = course.is_featured
    await _transition_status(db, course, CourseStatus.draft)
    await audit_repo.record(
        db, actor_id=owner.id, action="course.unpublish", target_type="course", target_id=course.id
    )
    if was_featured:
        await audit_repo.record(
            db,
            actor_id=owner.id,
            action="course.unfeatured",
            target_type="course",
            target_id=course.id,
        )
    await _bump_catalog_cache_version()
    return course


async def archive_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner archives a course (*→archived). Atomic force-private + unfeature;
    moderation_state stays sticky. Audits ``course.archive``.

    ``archive`` is lifecycle, not sharing — no feature flag. ``_transition_status``
    applies the same force-private + unfeature side-effect it does on unpublish
    (the ``target in (draft, archived)`` branch, ADR-0026 §4), so an archived
    course can never remain public/featured. moderation_state is left untouched
    (sticky, R-C2) so re-approval history survives an archive→draft→share cycle.
    """
    course = await _owned_course(db, course_id, owner)
    was_featured = course.is_featured
    await _transition_status(db, course, CourseStatus.archived)
    await audit_repo.record(
        db, actor_id=owner.id, action="course.archive", target_type="course", target_id=course.id
    )
    if was_featured:
        await audit_repo.record(
            db,
            actor_id=owner.id,
            action="course.unfeatured",
            target_type="course",
            target_id=course.id,
        )
    await _bump_catalog_cache_version()
    return course


async def restore_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner restores an archived course back to draft (archived→draft).

    The only legal transition out of ``archived`` (ADR-0026 §4 / the state
    machine). Visibility/featured were already forced private/off on archive and
    stay that way; moderation_state stays sticky. Audits ``course.restore``.
    """
    course = await _owned_course(db, course_id, owner)
    await _transition_status(db, course, CourseStatus.draft)
    await audit_repo.record(
        db, actor_id=owner.id, action="course.restore", target_type="course", target_id=course.id
    )
    await _bump_catalog_cache_version()
    return course


def _reshare_target_state(events: list[ModerationEvent]) -> ModerationState:
    """R-M9: re-share returns to ``approved`` iff there is a prior approval with
    NO later reject/delist; otherwise ``pending_review``. ``events`` newest-first.
    """
    for ev in events:  # newest-first
        if ev.to_state in (ModerationState.rejected.value, ModerationState.delisted.value):
            return ModerationState.pending_review
        if ev.to_state == ModerationState.approved.value:
            return ModerationState.approved
    return ModerationState.pending_review


async def share_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner shares a published course publicly (private→public).

    Requires ``status==published`` and ``can_publish_public(owner)``. Sets
    ``visibility=public`` and ``moderation_state`` to the re-approval target
    (R-M9): ``approved`` only if a prior approval with no later reject/delist
    exists, else ``pending_review``. Runs the advisory classifier (never
    auto-approves; fail-closed). Emits a ``ModerationEvent`` + ``course.shared``
    audit. **Does NOT list** unless the resolved state is ``approved``.
    """
    course = await _owned_course(db, course_id, owner)
    if course.status != CourseStatus.published:  # noqa: published-check — state-machine write
        raise ValidationAppError(
            "Only a published course can be shared publicly", code="course.invalid_transition"
        )
    if not visibility_service.can_publish_public(owner):
        raise ForbiddenError("You cannot publish publicly", code="course.publish_public_forbidden")

    from_state = str(course.moderation_state)
    events = await courses_repo.moderation_events_for_course(db, course.id)
    target = _reshare_target_state(events)

    # Advisory classifier — sets queue priority only, NEVER auto-approves.
    signal = moderation_safety.classify(
        title=course.title, overview=course.overview, outcomes=list(course.learning_outcomes or [])
    )

    course.visibility = Visibility.public
    course.moderation_state = target
    await _write_moderation_event(
        db,
        course=course,
        actor_id=owner.id,
        from_state=from_state,
        to_state=str(target),
        classifier_signal=signal.to_payload(),
    )
    await audit_repo.record(
        db, actor_id=owner.id, action="course.shared", target_type="course", target_id=course.id
    )
    await _bump_catalog_cache_version()
    if target == ModerationState.approved:
        # Re-listed without a fresh admin pass (R-M9) — refresh public RAG.
        _schedule_embedding_index(course.id)
    return course


async def unshare_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner unshares (public→private). moderation_state stays STICKY (NOT
    reset to none — corrects spec L457). Unfeatures. Audits ``course.unshared``."""
    course = await _owned_course(db, course_id, owner)
    was_featured = course.is_featured
    course.visibility = Visibility.private
    course.is_featured = False
    await audit_repo.record(
        db, actor_id=owner.id, action="course.unshared", target_type="course", target_id=course.id
    )
    if was_featured:
        await audit_repo.record(
            db,
            actor_id=owner.id,
            action="course.unfeatured",
            target_type="course",
            target_id=course.id,
        )
    await _bump_catalog_cache_version()
    return course


async def resubmit_course(db: AsyncSession, *, course_id: str, owner: User) -> Course:
    """Owner resubmits a rejected/delisted course for review (→pending_review).

    Re-runs the advisory classifier; emits a ``ModerationEvent`` + audit. The
    course must currently be public (sharing intent) and not already approved.
    """
    course = await _owned_course(db, course_id, owner)
    if course.moderation_state not in (
        ModerationState.rejected,
        ModerationState.delisted,
    ):
        raise ValidationAppError(
            "Only a rejected or delisted course can be resubmitted",
            code="course.invalid_transition",
        )
    from_state = str(course.moderation_state)
    signal = moderation_safety.classify(
        title=course.title, overview=course.overview, outcomes=list(course.learning_outcomes or [])
    )
    course.moderation_state = ModerationState.pending_review
    await _write_moderation_event(
        db,
        course=course,
        actor_id=owner.id,
        from_state=from_state,
        to_state=str(ModerationState.pending_review),
        classifier_signal=signal.to_payload(),
    )
    await audit_repo.record(
        db,
        actor_id=owner.id,
        action="course.resubmitted",
        target_type="course",
        target_id=course.id,
    )
    return course


async def _unique_slug(db: AsyncSession, title: str, *, exclude_id: str | None = None) -> str:
    """Mint a course slug that isn't claimed by any existing row.

    The check must include soft-deleted courses because the DB unique
    constraint on ``courses.slug`` is unconditional — handing back a
    soft-deleted course's slug would crash the next INSERT.
    """
    base = slugify(title)[:180] or "course"
    for n in range(1, 51):
        candidate = base if n == 1 else f"{base}-{n}"
        if not await courses_repo.slug_is_taken(db, candidate, exclude_id=exclude_id):
            return candidate
    return f"{base}-{new_id()[:6]}"


async def _flush_course_with_slug_retry(
    db: AsyncSession, course: Course, *, title: str, attempts: int = 3
) -> None:
    """Flush a pending ``Course`` insert with optimistic slug-collision retry.

    ``_unique_slug`` runs a non-locking SELECT, so two concurrent creates
    that mint the same slug both pass the check and only one INSERT wins;
    the other crashes with ``IntegrityError`` → 500. We re-attempt inside
    a SAVEPOINT (so the outer request transaction stays clean), assigning
    a short random suffix on each retry to make collision effectively
    impossible. Three attempts is enough for any plausible level of
    concurrency; past that we give up with a clean 409.
    """
    base = slugify(title)[:180] or "course"
    for attempt in range(attempts):
        try:
            async with db.begin_nested():
                await db.flush()
            return
        except IntegrityError as exc:
            # Only swallow slug collisions — anything else (FK violation,
            # NOT NULL on another column) should propagate as the real
            # error it is.
            msg = (str(getattr(exc, "orig", "")) + " " + str(exc)).lower()
            if "slug" not in msg:
                raise
            if attempt == attempts - 1:
                raise ConflictError(
                    "Could not allocate a unique slug after retries",
                    code="course.slug_race",
                ) from exc
            course.slug = f"{base}-{new_id()[:6]}"


# ---------- Modules ----------


async def create_module(
    db: AsyncSession, *, course_id: str, owner: User, payload: ModuleCreate
) -> Module:
    course = await _owned_course(db, course_id, owner)
    order = await courses_repo.next_module_order(db, course.id)
    mod = Module(
        course_id=course.id, title=payload.title, description=payload.description, order=order
    )
    db.add(mod)
    await db.flush()
    return mod


async def update_module(
    db: AsyncSession, *, module_id: str, owner: User, payload: ModuleUpdate
) -> Module:
    mod = await _owned_module(db, module_id, owner)
    if payload.title is not None:
        mod.title = payload.title
    if payload.description is not None:
        mod.description = payload.description
    return mod


async def delete_module(db: AsyncSession, *, module_id: str, owner: User) -> None:
    mod = await _owned_module(db, module_id, owner)
    await db.delete(mod)


async def reorder_modules(
    db: AsyncSession, *, course_id: str, owner: User, mapping: dict[str, int]
) -> None:
    course = await _owned_course(db, course_id, owner)
    modules = await courses_repo.list_modules_for_course(db, course.id)
    by_id = {m.id: m for m in modules}
    _validate_complete_order(mapping, present_ids=set(by_id.keys()), kind="modules")
    # Two-phase update to avoid uq constraint conflicts.
    for m in modules:
        m.order = -1 - m.order  # temp negative
    await db.flush()
    for mid, target in mapping.items():
        by_id[mid].order = int(target)


# ---------- Lessons ----------


async def create_lesson(
    db: AsyncSession, *, module_id: str, owner: User, payload: LessonCreate
) -> Lesson:
    mod = await _owned_module(db, module_id, owner)
    if payload.data.type != payload.type.value:
        raise ValidationAppError(
            "Lesson type and payload type mismatch", code="lesson.type_mismatch"
        )
    order = await courses_repo.next_lesson_order(db, mod.id)
    lesson = Lesson(
        module_id=mod.id,
        title=payload.title,
        type=LessonType(payload.type.value),
        order=order,
        duration_seconds=payload.duration_seconds,
        is_preview=payload.is_preview,
        data=payload.data.model_dump(),
    )
    db.add(lesson)
    await db.flush()
    return lesson


async def update_lesson(
    db: AsyncSession, *, lesson_id: str, owner: User, payload: LessonUpdate
) -> Lesson:
    lesson = await _owned_lesson(db, lesson_id, owner)
    if payload.title is not None:
        lesson.title = payload.title
    if payload.duration_seconds is not None:
        lesson.duration_seconds = payload.duration_seconds
    if payload.is_preview is not None:
        lesson.is_preview = payload.is_preview
    if payload.data is not None:
        # `lesson.type` is a String column (Mapped[LessonType]
        # without a TypeDecorator) → str at read time, no .value.
        if payload.data.type != str(lesson.type):
            raise ValidationAppError(
                "Cannot change lesson type via update", code="lesson.type_immutable"
            )
        lesson.data = payload.data.model_dump()
    return lesson


async def delete_lesson(db: AsyncSession, *, lesson_id: str, owner: User) -> None:
    lesson = await _owned_lesson(db, lesson_id, owner)
    lesson.deleted_at = datetime.now(UTC)


async def reorder_lessons(
    db: AsyncSession, *, module_id: str, owner: User, mapping: dict[str, int]
) -> None:
    mod = await _owned_module(db, module_id, owner)
    # The relationship returns soft-deleted lessons too. Callers shouldn't
    # have to know about them, so the mapping is validated against *live*
    # ids only — but we still have to nudge soft-deleted rows out of the
    # way during the two-phase update or they collide with the new
    # positive orders via the (module_id, order) unique constraint.
    all_lessons = list(mod.lessons)
    live = [lesson for lesson in all_lessons if lesson.deleted_at is None]
    by_id = {lesson.id: lesson for lesson in live}
    _validate_complete_order(mapping, present_ids=set(by_id.keys()), kind="lessons")
    for lesson in all_lessons:
        lesson.order = -1 - lesson.order  # temp negative
    await db.flush()
    for lid, target in mapping.items():
        by_id[lid].order = int(target)
    # Park soft-deleted rows just past the live range so they can't
    # collide with another lesson's order on the next reorder either.
    n = len(live)
    for i, lesson in enumerate(
        sorted(
            (lsn for lsn in all_lessons if lsn.deleted_at is not None),
            key=lambda lsn: lsn.id,  # deterministic ordering
        )
    ):
        lesson.order = n + i


# ---------- ownership guards ----------


async def _owned_course(db: AsyncSession, course_id: str, owner: User) -> Course:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if not _can_edit_course(owner, course):
        raise ForbiddenError("Not your course", code="course.forbidden")
    return course


async def _owned_module(db: AsyncSession, module_id: str, owner: User) -> Module:
    mod = await courses_repo.get_module(db, module_id)
    if not mod:
        raise NotFoundError("Module not found", code="module.not_found")
    course = await courses_repo.get_course(db, mod.course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if not _can_edit_course(owner, course):
        raise ForbiddenError("Not your module", code="module.forbidden")
    return mod


async def _owned_lesson(db: AsyncSession, lesson_id: str, owner: User) -> Lesson:
    lesson = await courses_repo.get_lesson(db, lesson_id)
    if not lesson:
        raise NotFoundError("Lesson not found", code="lesson.not_found")
    mod = await courses_repo.get_module(db, lesson.module_id)
    if mod is None:
        raise NotFoundError("Module not found", code="module.not_found")
    course = await courses_repo.get_course(db, mod.course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if not _can_edit_course(owner, course):
        raise ForbiddenError("Not your lesson", code="lesson.forbidden")
    return lesson


def _can_edit_course(user: User, course: Course) -> bool:
    """Owner-only mutation gate (FR-MOD-05 / S2.8).

    Narrowed from the old ``is_admin() OR owner`` rule: admins may VIEW any
    course but must act on non-owned courses through the moderation endpoints
    (S6), never through owner-shaped PATCH/DELETE. ``test_admin_cannot_edit_others_course``
    pins this; S6.5 owns the richer admin-moderation surface.
    """
    return course.owner_id == user.id


async def slug_or_id(db: AsyncSession, key: str, *, with_modules: bool = False) -> Course:
    course = await courses_repo.get_course(db, key, with_modules=with_modules)
    if course:
        return course
    course = await courses_repo.get_course_by_slug(db, key, with_modules=with_modules)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    return course


# ---------- Clone / remix (ADR-0028 §Decision.2; S4.6/S4.7) ----------

#: Logical operation guarded by ``Idempotency-Key`` (ADR-0028 §"New model").
_CLONE_ENDPOINT = "course.clone"


async def _assert_clone_quotas(db: AsyncSession, caller: User) -> None:
    """Pre-flight non-dollar amplification guards (S4.7 / FR-CLONE-18, R-S7).

    A clone is platform compute/storage, not an LLM call, so it never rides the
    24h-dollar guard (charter decision 4/5). Two durable DB COUNTs:

    * **Rate window** — recent ``course.cloned`` audit rows by this actor within
      the hour/day window → ``clone.rate_limited`` 429. Counting audit rows
      (not an in-memory counter) survives worker restarts; slowapi is the fast
      first line wired on the route.
    * **Owned-course cap** — live (non-soft-deleted) courses owned by the caller
      → ``clone.course_limit`` 409. Bounds clone-of-clone amplification.
    """
    s = get_settings()
    now = datetime.now(UTC)

    from sqlalchemy import func, select

    from app.models.audit import AuditEvent

    # Per-hour then per-day clone-window COUNT over audit rows (durable).
    for window_seconds, limit in (
        (3600, s.clone_per_hour),
        (86400, s.clone_per_day),
    ):
        since = now - timedelta(seconds=window_seconds)
        recent = (
            await db.execute(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.actor_id == caller.id,
                    AuditEvent.action == "course.cloned",
                    AuditEvent.created_at >= since,
                )
            )
        ).scalar_one()
        if int(recent) >= limit:
            raise CloneRateLimitedError(
                "You're cloning too fast — try again shortly.",
                details={"window_seconds": window_seconds, "limit": limit},
            )

    # Live-owned-course cap (FR-CLONE-18). Soft-deleted courses don't count.
    owned = (
        await db.execute(
            select(func.count(Course.id)).where(
                Course.owner_id == caller.id,
                Course.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if int(owned) >= s.clone_owned_cap:
        raise CloneCourseLimitError(
            "You've reached your course limit.",
            details={"limit": s.clone_owned_cap},
        )


async def clone_course(
    db: AsyncSession,
    *,
    caller: User,
    source_key: str,
    ip: str | None = None,
    user_agent: str | None = None,
    source_updated_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> Course:
    """Clone a publicly-listed course into a fresh private draft (ADR-0028 §2).

    The orchestrator: resolve + authorize (``is_publicly_listed`` with the
    403-vs-404 existence-hide split), idempotency replay, optional
    ``source_updated_at`` precondition, non-dollar quotas, sanitized-export
    projection (S4.3), atomic materialization with server-written immutable
    provenance, owner self-enroll (S4.4), audit ×2 + origin-owner notification,
    and idempotency-key record. The whole DB tree commits in the caller's single
    transaction so any failure rolls back to no orphan course (FR-CLONE-22). S3
    asset re-homing + embeddings are lazy/async (enqueued by the caller after
    commit — S4.9/S4.10).

    Authorization split (FR-CLONE-03, the security requirement — no existence
    leak): a source that is NOT ``is_publicly_listed`` raises ``403
    clone.source_not_clonable`` ONLY if the caller can otherwise view it (their
    own private draft); for anyone else it is an indistinguishable ``404
    course.not_found``. ``can_clone(caller)`` (capability) is re-checked here so
    enforcement is service-level, not route-only (FR-CLONE-02).
    """
    # ---- Resolve. A quarantined/delisted/soft-deleted source is loaded but
    # never publicly listed; the authorize step below existence-hides it. A
    # genuinely-absent slug/id raises 404 inside slug_or_id. ----
    source = await slug_or_id(db, source_key, with_modules=True)

    # ---- Authorize (403/404 split — route through the central authorizer,
    # never a raw status check). ----
    if not visibility_service.is_publicly_listed(source):
        if await visibility_service.can_view_course(db, source, caller):
            # Caller can see it (their own private draft) but it isn't listable.
            raise CloneSourceNotClonableError("This course cannot be cloned.")
        # Existence-hide: indistinguishable from a non-existent course.
        raise NotFoundError("Course not found", code="course.not_found")

    # Capability re-check (service-level, FR-CLONE-02). Suspended/inactive users
    # are already dropped at the route's CurrentUser dep; belt-and-suspenders.
    if not visibility_service.can_clone(source, caller) or not caller.is_active:
        raise ForbiddenError("You cannot clone this course", code="clone.source_not_clonable")

    # ---- Idempotency replay (FR-CLONE-20). A same-key retry returns the prior
    # committed clone; we do NOT re-enqueue the asset task (the tree is the
    # durable unit — ADR-0028 §"Open risks"). ----
    if idempotency_key:
        prior_id = await idempotency_service.lookup(
            db, user_id=caller.id, key=idempotency_key, endpoint=_CLONE_ENDPOINT
        )
        if prior_id:
            prior = await courses_repo.get_course(db, prior_id, with_modules=True)
            if prior is not None:
                return prior

    # ---- Optional precondition (FR-CLONE-14, best-effort — Course.updated_at
    # only bumps on a course-row write; snapshot atomicity is the real guard). ----
    # Compare to second granularity to tolerate ISO round-trip precision.
    if (
        source_updated_at is not None
        and source.updated_at is not None
        and int(source.updated_at.timestamp()) != int(source_updated_at.timestamp())
    ):
        raise CloneSourceChangedError("The source course changed — reload and retry.")

    # ---- Quotas (non-dollar, S4.7). ----
    await _assert_clone_quotas(db, caller)

    # ---- Project (S4.3 — the whitelist boundary). Size ceiling surfaces here. ----
    s = get_settings()
    modules = list(source.modules)
    lessons = [le for mod in modules for le in mod.lessons]
    try:
        export = clone_projection.build_export_projection(
            source,
            modules,
            lessons,
            max_lessons=s.clone_max_lessons,
            max_data_bytes=s.clone_max_data_bytes,
        )
    except clone_projection.CloneSourceTooLargeError as exc:
        raise CloneSourceTooLargeError(
            "This course is too large to clone.",
            details={"lessons": exc.lessons, "data_bytes": exc.data_bytes},
        ) from exc

    # ---- Materialize atomically (single transaction; dense orders satisfy the
    # uq_*_order constraints on first INSERT — NO two-phase reorder). ----
    new_course = Course(
        owner_id=caller.id,
        subject_id=export.subject_id,
        title=export.title,
        slug=await _unique_slug(db, export.title),
        overview=export.overview,
        difficulty=export.difficulty,
        cover_url=export.cover_url,
        learning_outcomes=list(export.learning_outcomes),
        status=CourseStatus.draft,
        visibility=Visibility.private,
        moderation_state=ModerationState.none,
        is_featured=False,
        published_at=None,
        # Provenance — SERVER-WRITTEN ONCE, never client-supplied (FR-CLONE-09).
        origin_course_id=source.id,
        origin_owner_id=source.owner_id,
        root_origin_course_id=source.root_origin_course_id or source.id,
        origin_title_snapshot=source.title,
        origin_owner_name_snapshot=source.owner.full_name,
        cloned_at=datetime.now(UTC),
    )
    # Tags are platform-shared — associate existing rows by id (never deep-copy).
    if export.tag_ids:
        new_course.tags = await courses_repo.list_tags_by_ids(db, export.tag_ids)
    db.add(new_course)
    await _flush_course_with_slug_retry(db, new_course, title=export.title)

    # module → lesson loop, dense pre-computed orders (mirrors commit_outline).
    for mod_export in export.modules:
        module = Module(
            course_id=new_course.id,
            title=mod_export.title,
            description=mod_export.description,
            order=mod_export.order,
        )
        db.add(module)
        await db.flush()
        for lesson_export in mod_export.lessons:
            lesson = Lesson(
                module_id=module.id,
                title=lesson_export.title,
                order=lesson_export.order,
                type=LessonType(lesson_export.type),
                duration_seconds=lesson_export.duration_seconds,
                is_preview=lesson_export.is_preview,  # forced False in projection
                data=lesson_export.data,
            )
            db.add(lesson)
        await db.flush()

    # ---- Owner self-enroll (FR-CLONE-16). MUST use enroll_self, never enroll()
    # (the clone is draft+private; enroll() rejects non-publicly-listed). ----
    from app.services import enrollment as enrollment_service

    await enrollment_service.enroll_self(db, user=caller, course=new_course)

    # ---- Audit ×2 + origin-owner notification (FR-CLONE-19), atomic with the
    # tree. ``asset_copy_failures`` starts empty; the lazy asset task appends. ----
    audit_data = {
        "origin_course_id": source.id,
        "origin_owner_id": source.owner_id,
        "root_origin_course_id": new_course.root_origin_course_id,
        "lessons_copied": export.lessons_copied,
        "modules_copied": export.modules_copied,
        "modules_dropped": export.modules_dropped,
        "asset_copy_failures": [],
    }
    await audit_repo.record(
        db,
        actor_id=caller.id,
        action="course.cloned",
        target_type="course",
        target_id=new_course.id,
        ip_address=ip,
        user_agent=user_agent,
        data=audit_data,
    )
    # Second event targets the ORIGIN course (FR-CLONE-24 "who cloned this").
    await audit_repo.record(
        db,
        actor_id=caller.id,
        action="course.cloned_by_other",
        target_type="course",
        target_id=source.id,
        ip_address=ip,
        user_agent=user_agent,
        data={"clone_course_id": new_course.id, "cloned_by": caller.id},
    )
    # Notify the origin owner (display-name only; gated by their prefs). Skip a
    # self-clone — no point telling someone they cloned their own course.
    if source.owner_id != caller.id:
        await notifications_repo.create(
            db,
            user_id=source.owner_id,
            kind=NotificationKind.course_cloned,
            title=f"Someone made a copy of {source.title}",
            body=f"{caller.full_name} cloned your course.",
            data={"origin_course_id": source.id, "clone_course_id": new_course.id},
        )

    # ---- Record the idempotency key pointing at the committed clone. ----
    if idempotency_key:
        await idempotency_service.record(
            db,
            user_id=caller.id,
            key=idempotency_key,
            endpoint=_CLONE_ENDPOINT,
            response_target_id=new_course.id,
        )

    return new_course


def enqueue_clone_assets(course_id: str) -> None:
    """Best-effort post-commit enqueue of the lazy asset re-homing task (S4.9).

    Mirrors the defensive :func:`_schedule_embedding_index` shape (CLAUDE.md:
    Celery is best-effort in dev) — a down broker logs a warning and the clone
    still succeeds; the orphan sweeper + on-demand re-home reconcile later. The
    DB tree is the durable unit, so this fires AFTER the request commits.
    """
    try:
        from app.workers.tasks.media import copy_clone_assets

        copy_clone_assets.delay(course_id)
    except Exception:  # pragma: no cover — broker may be down
        log.warning("clone_assets_enqueue_failed", course_id=course_id)


async def resolve_origin(db: AsyncSession, course: Course):
    """Read-time clone provenance resolution (S4.8 / DR-19, FR-CLONE-10).

    Returns a :class:`CourseOrigin` (or ``None`` for a from-scratch course)
    where:

    * ``origin_available`` re-resolves ``origin_course_id`` through
      ``is_publicly_listed`` — a single indexed lookup
      (``ix_courses_origin_course_id``). False when the source went
      private/delisted/quarantined/soft-deleted, suppressing the source link
      (FR-DEL-01) while the snapshot title still renders.
    * ``origin_owner_name`` is overridden to the localized deleted-user label
      key at READ time when the origin owner is tombstoned (``deleted_at IS NOT
      NULL``) OR ``origin_owner_id IS NULL`` (hard purge) OR the stored snapshot
      already equals the one-time scrub sentinel — so PII anonymizes even if the
      S6 ``delete_account`` snapshot scrub never ran (DR-19: read-time, not
      one-time). Composes with S6's sentinel + the ``UserPublic`` tombstone path.
    """
    from app.schemas.course import build_course_origin
    from app.schemas.user import resolve_owner_display_name

    if getattr(course, "origin_course_id", None) is None:
        return None

    # origin_available: re-resolve the source and apply the listed predicate.
    origin_available = False
    origin_source = await courses_repo.get_course(db, course.origin_course_id)
    if origin_source is not None and visibility_service.is_publicly_listed(origin_source):
        origin_available = True

    # Deleted-owner detection (ADR-0030 tombstone discriminator = deleted_at).
    owner_is_deleted = course.origin_owner_id is None
    if not owner_is_deleted and course.origin_owner_id is not None:
        owner = await db.get(User, course.origin_owner_id)
        owner_is_deleted = owner is None or owner.deleted_at is not None

    display_name = resolve_owner_display_name(
        course.origin_owner_name_snapshot, owner_is_deleted=owner_is_deleted
    )

    return build_course_origin(
        course,
        origin_available=origin_available,
        origin_owner_name=display_name,
    )


# ``can_view_course`` now lives in the central authorizer (ADR-0026 §3 / S2.4):
# it is imported at module top and re-exported via ``__all__`` so existing
# callers (courses.py, discussions.py, api/v1/discussions.py) keep their call
# sites unchanged while routing through the single visibility predicate
# (is_publicly_listed OR owner/admin/enrolled, with csam/illegal quarantine
# suppression). See the import + __all__ near the top of this module.
