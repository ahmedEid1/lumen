"""Course/module/lesson orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from slugify import slugify
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.ids import new_id
from app.models.course import Course, CourseStatus, Lesson, LessonType, Module
from app.models.user import User
from app.repositories import courses as courses_repo

if TYPE_CHECKING:
    from app.schemas.course import (
        CourseCreate,
        CourseUpdate,
        LessonCreate,
        LessonUpdate,
        ModuleCreate,
        ModuleUpdate,
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
    )
    if payload.tag_ids:
        course.tags = await courses_repo.list_tags_by_ids(db, payload.tag_ids)
    db.add(course)
    await db.flush()
    return course


async def update_course(
    db: AsyncSession, *, course_id: str, owner: User, payload: CourseUpdate
) -> Course:
    course = await _owned_course(db, course_id, owner)
    if payload.title is not None and payload.title != course.title:
        course.title = payload.title
        course.slug = await _unique_slug(db, payload.title, exclude_id=course.id)
    if payload.subject_id is not None and payload.subject_id != course.subject_id:
        subject = await courses_repo.get_subject(db, payload.subject_id)
        if not subject:
            raise NotFoundError("Subject not found", code="subject.not_found")
        course.subject_id = subject.id
    if payload.overview is not None:
        course.overview = payload.overview
    if payload.difficulty is not None:
        course.difficulty = payload.difficulty
    if payload.cover_url is not None:
        course.cover_url = payload.cover_url
    if payload.tag_ids is not None:
        course.tags = await courses_repo.list_tags_by_ids(db, payload.tag_ids)
    if payload.status is not None:
        prev = course.status
        await _transition_status(course, payload.status)
        if prev != course.status:
            _schedule_index(course.id)
    return course


async def delete_course(db: AsyncSession, *, course_id: str, owner: User) -> None:
    course = await _owned_course(db, course_id, owner)
    course.deleted_at = datetime.now(timezone.utc)
    _schedule_index(course.id)


def _schedule_index(course_id: str) -> None:
    """Best-effort: enqueue a search reindex. Tolerates broker being down in dev/tests."""
    try:
        from app.workers.tasks.search import index_course

        index_course.delay(course_id)
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger

        get_logger(__name__).info("search_index_skipped", course_id=course_id)


async def duplicate_course(db: AsyncSession, *, source_id: str, owner: User) -> Course:
    """Clone a course (modules + lessons) as a draft owned by ``owner``.

    The caller does not need to own the source — instructors can copy any
    published course to remix it. Drafts are not visible to anyone but the
    owner / admins.
    """
    if not owner.is_instructor_or_admin():
        raise ForbiddenError("Only instructors can duplicate courses", code="courses.forbidden")

    source = await courses_repo.get_course(db, source_id, with_modules=True)
    if not source:
        raise NotFoundError("Course not found", code="course.not_found")

    new_title = f"{source.title} (copy)"
    slug = await _unique_slug(db, new_title)
    cloned = Course(
        owner_id=owner.id,
        subject_id=source.subject_id,
        title=new_title,
        slug=slug,
        overview=source.overview,
        cover_url=source.cover_url,
        difficulty=source.difficulty,
        status=CourseStatus.draft,
        is_featured=False,
    )
    # tags are shared; the relationship is many-to-many so we can re-attach by reference.
    cloned.tags = list(source.tags)
    db.add(cloned)
    await db.flush()

    for src_module in sorted(source.modules, key=lambda m: m.order):
        mod = Module(
            course_id=cloned.id,
            title=src_module.title,
            description=src_module.description,
            order=src_module.order,
        )
        db.add(mod)
        await db.flush()
        for src_lesson in sorted(src_module.lessons, key=lambda lesson: lesson.order):
            if src_lesson.deleted_at is not None:
                continue
            db.add(
                Lesson(
                    module_id=mod.id,
                    title=src_lesson.title,
                    type=src_lesson.type,
                    order=src_lesson.order,
                    duration_seconds=src_lesson.duration_seconds,
                    is_preview=src_lesson.is_preview,
                    data=dict(src_lesson.data or {}),
                )
            )
    await db.flush()
    return cloned


async def _transition_status(course: Course, target: CourseStatus) -> None:
    if course.status == target:
        return
    valid = {
        CourseStatus.draft: {CourseStatus.published, CourseStatus.archived},
        CourseStatus.published: {CourseStatus.draft, CourseStatus.archived},
        CourseStatus.archived: {CourseStatus.draft},
    }
    if target not in valid[course.status]:
        raise ValidationAppError(
            f"Invalid transition {course.status} → {target}", code="course.invalid_transition"
        )
    if target == CourseStatus.published:
        if not course.title or not course.overview:
            raise ValidationAppError(
                "Course must have a title and overview to publish", code="course.missing_fields"
            )
        course.published_at = datetime.now(timezone.utc)
    course.status = target


async def _unique_slug(db: AsyncSession, title: str, *, exclude_id: str | None = None) -> str:
    """Mint a course slug that isn't claimed by any existing row.

    The check must include soft-deleted courses because the DB unique
    constraint on ``courses.slug`` is unconditional — handing back a
    soft-deleted course's slug would crash the next INSERT.
    """
    base = slugify(title)[:180] or "course"
    candidate = base
    n = 1
    while True:
        if not await courses_repo.slug_is_taken(db, candidate, exclude_id=exclude_id):
            return candidate
        n += 1
        candidate = f"{base}-{n}"
        if n > 50:
            return f"{base}-{new_id()[:6]}"


# ---------- Modules ----------


async def create_module(db: AsyncSession, *, course_id: str, owner: User, payload: ModuleCreate) -> Module:
    course = await _owned_course(db, course_id, owner)
    order = await courses_repo.next_module_order(db, course.id)
    mod = Module(course_id=course.id, title=payload.title, description=payload.description, order=order)
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


async def reorder_modules(db: AsyncSession, *, course_id: str, owner: User, mapping: dict[str, int]) -> None:
    course = await _owned_course(db, course_id, owner)
    modules = await courses_repo.list_modules_for_course(db, course.id)
    by_id = {m.id: m for m in modules}
    unknown = [k for k in mapping if k not in by_id]
    if unknown:
        raise ValidationAppError("Unknown module ids", code="modules.unknown", details={"ids": unknown})
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
        raise ValidationAppError("Lesson type and payload type mismatch", code="lesson.type_mismatch")
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
        if payload.data.type != lesson.type.value:
            raise ValidationAppError("Cannot change lesson type via update", code="lesson.type_immutable")
        lesson.data = payload.data.model_dump()
    return lesson


async def delete_lesson(db: AsyncSession, *, lesson_id: str, owner: User) -> None:
    lesson = await _owned_lesson(db, lesson_id, owner)
    lesson.deleted_at = datetime.now(timezone.utc)


async def reorder_lessons(
    db: AsyncSession, *, module_id: str, owner: User, mapping: dict[str, int]
) -> None:
    mod = await _owned_module(db, module_id, owner)
    by_id = {lesson.id: lesson for lesson in mod.lessons}
    unknown = [k for k in mapping if k not in by_id]
    if unknown:
        raise ValidationAppError("Unknown lesson ids", code="lessons.unknown", details={"ids": unknown})
    for lesson in mod.lessons:
        lesson.order = -1 - lesson.order
    await db.flush()
    for lid, target in mapping.items():
        by_id[lid].order = int(target)


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
    return user.is_admin() or course.owner_id == user.id


async def slug_or_id(db: AsyncSession, key: str, *, with_modules: bool = False) -> Course:
    course = await courses_repo.get_course(db, key, with_modules=with_modules)
    if course:
        return course
    course = await courses_repo.get_course_by_slug(db, key, with_modules=with_modules)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    return course


async def can_view_unpublished(course: Course, viewer: User | None) -> bool:
    """Synchronous yes/no without enrollment lookup.

    Prefer :func:`can_view_course` in handlers that already have a db session
    — it also lets enrolled learners keep reading courses after they're
    archived or moved back to draft.
    """
    if course.status == CourseStatus.published:
        return True
    if viewer is None:
        return False
    return viewer.is_admin() or course.owner_id == viewer.id


async def can_view_course(
    db: AsyncSession, course: Course, viewer: User | None
) -> bool:
    """Authoritative visibility check for the course detail endpoint.

    Returns True for published courses, owners, admins, OR for learners who
    are currently enrolled (regardless of course status). The last branch is
    important: an instructor who archives a course must not lock out the
    learners already paying it down.
    """
    if course.status == CourseStatus.published:
        return True
    if viewer is None:
        return False
    if viewer.is_admin() or course.owner_id == viewer.id:
        return True
    enrollment = await courses_repo.get_enrollment(
        db, user_id=viewer.id, course_id=course.id
    )
    return enrollment is not None
