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
from app.models.course import Course, CourseStatus, Lesson, LessonType, Module
from app.models.user import User
from app.repositories import courses as courses_repo

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
