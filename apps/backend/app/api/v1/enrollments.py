"""Enrollment + per-lesson progress."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import (
    CourseListItem,
    EnrollmentOut,
    ProgressUpdate,
    SubjectOut,
    TagOut,
)
from app.schemas.user import UserPublic
from app.services import enrollment as enrollment_service

router = APIRouter()


@router.get("/enrollments", response_model=list[EnrollmentOut])
async def list_my_enrollments(user: CurrentUser, db: DBSession) -> list[EnrollmentOut]:
    enrollments = await courses_repo.list_enrollments_for_user(db, user.id)
    stats = await courses_repo.stats_for_courses(db, [e.course_id for e in enrollments])
    out: list[EnrollmentOut] = []
    for e in enrollments:
        pct = await enrollment_service.progress_pct(db, enrollment=e)
        s = stats.get(e.course_id, {})
        c = e.course
        out.append(
            EnrollmentOut(
                id=e.id,
                created_at=e.created_at,
                completed_at=e.completed_at,
                certificate_id=e.certificate_id,
                progress_pct=pct,
                course=CourseListItem(
                    id=c.id, title=c.title, slug=c.slug, overview=c.overview, difficulty=c.difficulty,
                    cover_url=c.cover_url, status=c.status, is_featured=c.is_featured,
                    published_at=c.published_at, created_at=c.created_at,
                    owner=UserPublic.model_validate(c.owner),
                    subject=SubjectOut.model_validate(c.subject),
                    tags=[TagOut.model_validate(t) for t in c.tags],
                    modules_count=int(s.get("modules_count", 0) or 0),
                    enrollments_count=int(s.get("enrollments_count", 0) or 0),
                    avg_rating=s.get("avg_rating"),
                ),
            )
        )
    return out


@router.post("/enrollments/{course_id}", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
async def enroll(course_id: str, user: CurrentUser, db: DBSession) -> EnrollmentOut:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    enrollment = await enrollment_service.enroll(db, user=user, course=course)
    pct = await enrollment_service.progress_pct(db, enrollment=enrollment)
    stats = (await courses_repo.stats_for_courses(db, [course.id])).get(course.id, {})
    return EnrollmentOut(
        id=enrollment.id,
        created_at=enrollment.created_at,
        completed_at=enrollment.completed_at,
        certificate_id=enrollment.certificate_id,
        progress_pct=pct,
        course=CourseListItem(
            id=course.id, title=course.title, slug=course.slug, overview=course.overview,
            difficulty=course.difficulty, cover_url=course.cover_url, status=course.status,
            is_featured=course.is_featured, published_at=course.published_at, created_at=course.created_at,
            owner=UserPublic.model_validate(course.owner),
            subject=SubjectOut.model_validate(course.subject),
            tags=[TagOut.model_validate(t) for t in course.tags],
            modules_count=int(stats.get("modules_count", 0) or 0),
            enrollments_count=int(stats.get("enrollments_count", 0) or 0),
            avg_rating=stats.get("avg_rating"),
        ),
    )


@router.delete("/enrollments/{course_id}", response_model=OkResponse)
async def unenroll(course_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    await enrollment_service.unenroll(db, user=user, course=course)
    return OkResponse()


@router.post("/progress/lessons/{lesson_id}", response_model=dict)
async def mark_lesson_progress(
    lesson_id: str, payload: ProgressUpdate, user: CurrentUser, db: DBSession
) -> dict:
    lesson = await courses_repo.get_lesson(db, lesson_id)
    if not lesson:
        raise NotFoundError("Lesson not found", code="lesson.not_found")
    enrollment, lp, pct = await enrollment_service.mark_lesson(
        db, user=user, lesson=lesson, completed=payload.completed, payload=payload.payload
    )
    return {
        "lesson_id": lesson.id,
        "completed_at": lp.completed_at.isoformat() if lp.completed_at else None,
        "progress_pct": pct,
        "certificate_id": enrollment.certificate_id,
    }
