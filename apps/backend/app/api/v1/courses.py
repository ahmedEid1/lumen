"""Course / module / lesson endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DBSession, OptionalUser, RequireInstructor
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
    SubjectOut,
    TagOut,
)
from app.schemas.user import UserPublic
from app.services import courses as courses_service
from app.services import enrollment as enrollment_service

router = APIRouter()


def _course_to_detail(course, modules, stats, *, is_enrolled: bool, progress_pct: float) -> CourseDetail:
    return CourseDetail(
        id=course.id,
        title=course.title,
        slug=course.slug,
        overview=course.overview,
        difficulty=course.difficulty,
        cover_url=course.cover_url,
        status=course.status,
        is_featured=course.is_featured,
        published_at=course.published_at,
        created_at=course.created_at,
        owner=UserPublic.model_validate(course.owner),
        subject=SubjectOut.model_validate(course.subject),
        tags=[TagOut.model_validate(t) for t in course.tags],
        modules_count=int(stats.get("modules_count", 0) or 0),
        enrollments_count=int(stats.get("enrollments_count", 0) or 0),
        avg_rating=stats.get("avg_rating"),
        modules=[
            ModuleOut(
                id=m.id,
                title=m.title,
                description=m.description,
                order=m.order,
                lessons=[
                    LessonOut.model_validate(lesson)
                    for lesson in m.lessons
                    if getattr(lesson, "deleted_at", None) is None
                ],
            )
            for m in modules
        ],
        is_enrolled=is_enrolled,
        progress_pct=progress_pct,
    )


# ---------- Course CRUD ----------


@router.post("", response_model=CourseListItem, status_code=status.HTTP_201_CREATED)
async def create_course(payload: CourseCreate, user: RequireInstructor, db: DBSession) -> CourseListItem:
    course = await courses_service.create_course(db, user, payload)
    course = await courses_repo.get_course(db, course.id)
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    return CourseListItem(
        id=course.id, title=course.title, slug=course.slug, overview=course.overview, difficulty=course.difficulty,
        cover_url=course.cover_url, status=course.status, is_featured=course.is_featured,
        published_at=course.published_at, created_at=course.created_at,
        owner=UserPublic.model_validate(course.owner), subject=SubjectOut.model_validate(course.subject),
        tags=[TagOut.model_validate(t) for t in course.tags],
        modules_count=int(stats.get("modules_count", 0) or 0),
        enrollments_count=int(stats.get("enrollments_count", 0) or 0),
        avg_rating=stats.get("avg_rating"),
    )


@router.get("/mine", response_model=list[CourseListItem])
async def my_courses(user: RequireInstructor, db: DBSession) -> list[CourseListItem]:
    courses, _ = await courses_repo.search_courses(
        db, owner_id=user.id, only_published=False, page=1, page_size=100
    )
    stats = await courses_repo.stats_for_courses(db, [c.id for c in courses])
    return [
        CourseListItem(
            id=c.id, title=c.title, slug=c.slug, overview=c.overview, difficulty=c.difficulty,
            cover_url=c.cover_url, status=c.status, is_featured=c.is_featured,
            published_at=c.published_at, created_at=c.created_at,
            owner=UserPublic.model_validate(c.owner), subject=SubjectOut.model_validate(c.subject),
            tags=[TagOut.model_validate(t) for t in c.tags],
            modules_count=int(stats.get(c.id, {}).get("modules_count", 0) or 0),
            enrollments_count=int(stats.get(c.id, {}).get("enrollments_count", 0) or 0),
            avg_rating=stats.get(c.id, {}).get("avg_rating"),
        )
        for c in courses
    ]


@router.get("/{key}", response_model=CourseDetail)
async def get_course(key: str, viewer: OptionalUser, db: DBSession) -> CourseDetail:
    course = await courses_service.slug_or_id(db, key, with_modules=True)
    if not await courses_service.can_view_unpublished(course, viewer):
        from app.core.errors import NotFoundError

        raise NotFoundError("Course not found", code="course.not_found")

    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    is_enrolled = False
    pct = 0.0
    if viewer:
        enrollment = await courses_repo.get_enrollment(db, user_id=viewer.id, course_id=course.id)
        if enrollment:
            is_enrolled = True
            pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
    modules = [m for m in course.modules]
    return _course_to_detail(course, modules, stats, is_enrolled=is_enrolled, progress_pct=pct)


@router.patch("/{course_id}", response_model=CourseDetail)
async def update_course(
    course_id: str, payload: CourseUpdate, user: RequireInstructor, db: DBSession
) -> CourseDetail:
    await courses_service.update_course(db, course_id=course_id, owner=user, payload=payload)
    course = await courses_repo.get_course(db, course_id, with_modules=True)
    if course is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Course not found", code="course.not_found")
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    pct = 0.0
    is_enrolled = False
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if enrollment:
        is_enrolled = True
        pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
    return _course_to_detail(course, list(course.modules), stats, is_enrolled=is_enrolled, progress_pct=pct)


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
        id=mod.id, title=mod.title, description=mod.description, order=mod.order,
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
