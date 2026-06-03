"""Course/module/lesson orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
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
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import courses as courses_repo
from app.services import moderation_safety
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
    if not owner.is_instructor_or_admin():
        raise ForbiddenError("Only instructors can create courses", code="courses.forbidden")

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
    if payload.status is not None:
        await _transition_status(db, course, payload.status)
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


# ``can_view_course`` now lives in the central authorizer (ADR-0026 §3 / S2.4):
# it is imported at module top and re-exported via ``__all__`` so existing
# callers (courses.py, discussions.py, api/v1/discussions.py) keep their call
# sites unchanged while routing through the single visibility predicate
# (is_publicly_listed OR owner/admin/enrolled, with csam/illegal quarantine
# suppression). See the import + __all__ near the top of this module.
