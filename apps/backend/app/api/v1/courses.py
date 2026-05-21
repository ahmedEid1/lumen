"""Course / module / lesson endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import DBSession, OptionalUser, RequireInstructor
from app.api.v1 import _builders
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.models.bookmark import Bookmark
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import (
    CourseCreate,
    CourseDetail,
    CourseListItem,
    CourseUpdate,
    LessonCreate,
    LessonOut,
    LessonUpdate,
    ModuleCreate,
    ModuleOut,
    ModuleUpdate,
    OrderUpdateRequest,
)
from app.services import analytics as analytics_service
from app.services import courses as courses_service
from app.services import enrollment as enrollment_service

router = APIRouter()


# ---------- Course CRUD ----------


@router.post("", response_model=CourseListItem, status_code=status.HTTP_201_CREATED)
async def create_course(payload: CourseCreate, user: RequireInstructor, db: DBSession) -> CourseListItem:
    course = await courses_service.create_course(db, user, payload)
    refreshed = await courses_repo.get_course(db, course.id)
    if refreshed is None:
        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [refreshed.id])).get(refreshed.id, {})
    return _builders.list_item(refreshed, stats)


@router.get("/mine", response_model=list[CourseListItem])
async def my_courses(user: RequireInstructor, db: DBSession) -> list[CourseListItem]:
    courses, _ = await courses_repo.search_courses(
        db, owner_id=user.id, only_published=False, page=1, page_size=100
    )
    stats = await courses_repo.stats_for_courses(db, [c.id for c in courses])
    return [_builders.list_item(c, stats.get(c.id, {})) for c in courses]


@router.get("/{key}", response_model=CourseDetail)
async def get_course(key: str, viewer: OptionalUser, db: DBSession) -> CourseDetail:
    course = await courses_service.slug_or_id(db, key, with_modules=True)
    if not await courses_service.can_view_course(db, course, viewer):
        raise NotFoundError("Course not found", code="course.not_found")

    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    is_enrolled = False
    is_bookmarked = False
    pct = 0.0
    done: set[str] = set()
    if viewer:
        enrollment = await courses_repo.get_enrollment(db, user_id=viewer.id, course_id=course.id)
        if enrollment:
            is_enrolled = True
            pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
            done = await courses_repo.completed_lesson_ids(db, enrollment.id)
        is_bookmarked = (
            await db.execute(
                select(Bookmark.id).where(
                    Bookmark.user_id == viewer.id, Bookmark.course_id == course.id
                )
            )
        ).first() is not None
    return _builders.detail(
        course,
        list(course.modules),
        stats,
        is_enrolled=is_enrolled,
        is_bookmarked=is_bookmarked,
        progress_pct=pct,
        completed_lesson_ids=done,
    )


@router.patch("/{course_id}", response_model=CourseDetail)
async def update_course(
    course_id: str, payload: CourseUpdate, user: RequireInstructor, db: DBSession
) -> CourseDetail:
    await courses_service.update_course(db, course_id=course_id, owner=user, payload=payload)
    course = await courses_repo.get_course(db, course_id, with_modules=True)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    pct = 0.0
    is_enrolled = False
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if enrollment:
        is_enrolled = True
        pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
    return _builders.detail(
        course,
        list(course.modules),
        stats,
        is_enrolled=is_enrolled,
        is_bookmarked=False,
        progress_pct=pct,
    )


@router.delete("/{course_id}", response_model=OkResponse, status_code=status.HTTP_200_OK)
async def delete_course(course_id: str, user: RequireInstructor, db: DBSession) -> OkResponse:
    await courses_service.delete_course(db, course_id=course_id, owner=user)
    return OkResponse()


# ---------- Modules ----------


@router.post("/{course_id}/modules", response_model=ModuleOut, status_code=status.HTTP_201_CREATED)
async def create_module(
    course_id: str, payload: ModuleCreate, user: RequireInstructor, db: DBSession
) -> ModuleOut:
    mod = await courses_service.create_module(db, course_id=course_id, owner=user, payload=payload)
    return ModuleOut(
        id=mod.id, title=mod.title, description=mod.description, order=mod.order, lessons=[]
    )


@router.patch("/modules/{module_id}", response_model=ModuleOut)
async def update_module(
    module_id: str, payload: ModuleUpdate, user: RequireInstructor, db: DBSession
) -> ModuleOut:
    mod = await courses_service.update_module(db, module_id=module_id, owner=user, payload=payload)
    return ModuleOut(
        id=mod.id,
        title=mod.title,
        description=mod.description,
        order=mod.order,
        lessons=[LessonOut.model_validate(lesson) for lesson in mod.lessons if lesson.deleted_at is None],
    )


@router.delete("/modules/{module_id}", response_model=OkResponse)
async def delete_module(module_id: str, user: RequireInstructor, db: DBSession) -> OkResponse:
    await courses_service.delete_module(db, module_id=module_id, owner=user)
    return OkResponse()


@router.post("/{course_id}/modules/order", response_model=OkResponse)
async def reorder_modules(
    course_id: str, payload: OrderUpdateRequest, user: RequireInstructor, db: DBSession
) -> OkResponse:
    await courses_service.reorder_modules(db, course_id=course_id, owner=user, mapping=payload.order)
    return OkResponse()


# ---------- Lessons ----------


@router.post("/modules/{module_id}/lessons", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    module_id: str, payload: LessonCreate, user: RequireInstructor, db: DBSession
) -> LessonOut:
    lesson = await courses_service.create_lesson(db, module_id=module_id, owner=user, payload=payload)
    return LessonOut.model_validate(lesson)


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: str, payload: LessonUpdate, user: RequireInstructor, db: DBSession
) -> LessonOut:
    lesson = await courses_service.update_lesson(db, lesson_id=lesson_id, owner=user, payload=payload)
    return LessonOut.model_validate(lesson)


@router.delete("/lessons/{lesson_id}", response_model=OkResponse)
async def delete_lesson(lesson_id: str, user: RequireInstructor, db: DBSession) -> OkResponse:
    await courses_service.delete_lesson(db, lesson_id=lesson_id, owner=user)
    return OkResponse()


@router.post("/modules/{module_id}/lessons/order", response_model=OkResponse)
async def reorder_lessons(
    module_id: str, payload: OrderUpdateRequest, user: RequireInstructor, db: DBSession
) -> OkResponse:
    await courses_service.reorder_lessons(db, module_id=module_id, owner=user, mapping=payload.order)
    return OkResponse()


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def get_lesson(lesson_id: str, viewer: OptionalUser, db: DBSession) -> LessonOut:
    """Fetch a lesson for playback.

    Allowed when the viewer is enrolled, the course owner, an admin, or when
    the lesson is flagged ``is_preview`` (free preview) and the course is
    published.
    """
    lesson = await courses_repo.get_lesson(db, lesson_id)
    if lesson is None or lesson.deleted_at is not None:
        raise NotFoundError("Lesson not found", code="lesson.not_found")
    mod = await courses_repo.get_module(db, lesson.module_id)
    course = await courses_repo.get_course(db, mod.course_id) if mod else None
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")

    if lesson.is_preview and course.status.value == "published":
        return LessonOut.model_validate(lesson)
    if viewer is None:
        raise UnauthorizedError("Authentication required", code="auth.required")
    if viewer.is_admin() or course.owner_id == viewer.id:
        return LessonOut.model_validate(lesson)
    enrollment = await courses_repo.get_enrollment(db, user_id=viewer.id, course_id=course.id)
    if not enrollment:
        raise ForbiddenError("Enroll first", code="lesson.enroll_first")
    return LessonOut.model_validate(lesson)


# ---------- Analytics ----------


class CourseAnalyticsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    course_id: str
    enrollments: int
    completions: int
    completion_rate: float
    avg_rating: float | None = None
    rating_count: int
    avg_progress_pct: float
    enrollments_last_7d: int
    enrollments_last_30d: int


@router.get("/{course_id}/analytics", response_model=CourseAnalyticsOut)
async def course_analytics(
    course_id: str, user: RequireInstructor, db: DBSession
) -> CourseAnalyticsOut:
    data = await analytics_service.for_course(db, course_id=course_id, viewer=user)
    return CourseAnalyticsOut.model_validate(data)


# ---------- Cohort ----------


class CohortRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    full_name: str
    avatar_url: str | None = None
    enrolled_at: datetime
    completed_at: datetime | None = None
    progress_pct: float
    certificate_id: str | None = None


@router.get("/{course_id}/students", response_model=list[CohortRowOut])
async def course_cohort(
    course_id: str, user: RequireInstructor, db: DBSession
) -> list[CohortRowOut]:
    rows = await analytics_service.cohort_for_course(db, course_id=course_id, viewer=user)
    return [CohortRowOut.model_validate(r) for r in rows]


# ---------- Duplication ----------


@router.post("/{course_id}/duplicate", response_model=CourseListItem, status_code=status.HTTP_201_CREATED)
async def duplicate_course(
    course_id: str, user: RequireInstructor, db: DBSession
) -> CourseListItem:
    course = await courses_service.duplicate_course(db, source_id=course_id, owner=user)
    refreshed = await courses_repo.get_course(db, course.id)
    if refreshed is None:
        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [refreshed.id])).get(refreshed.id, {})
    return _builders.list_item(refreshed, stats)
