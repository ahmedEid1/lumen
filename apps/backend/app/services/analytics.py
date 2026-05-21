"""Per-course analytics for instructors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.course import Course, Enrollment, Lesson, LessonProgress, Module, Review
from app.models.user import User
from app.repositories import courses as courses_repo


@dataclass(slots=True)
class CourseAnalytics:
    course_id: str
    enrollments: int
    completions: int
    completion_rate: float          # 0..1
    avg_rating: float | None
    rating_count: int
    avg_progress_pct: float         # mean across enrollments, 0..100
    enrollments_last_7d: int
    enrollments_last_30d: int


async def for_course(db: AsyncSession, *, course_id: str, viewer: User) -> CourseAnalytics:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if not (viewer.is_admin() or course.owner_id == viewer.id):
        raise ForbiddenError("Not your course", code="analytics.forbidden")

    now = datetime.now(timezone.utc)
    seven = now - timedelta(days=7)
    thirty = now - timedelta(days=30)

    enrollments = int(
        (await db.execute(select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id))).scalar_one()
    )
    completions = int(
        (
            await db.execute(
                select(func.count(Enrollment.id)).where(
                    Enrollment.course_id == course.id, Enrollment.completed_at.is_not(None)
                )
            )
        ).scalar_one()
    )

    avg_rating_row = await db.execute(
        select(func.avg(Review.rating), func.count(Review.id))
        .where(Review.course_id == course.id, Review.deleted_at.is_(None))
    )
    avg_rating_val, rating_count = avg_rating_row.one()
    avg_rating: float | None = float(avg_rating_val) if avg_rating_val is not None else None

    total_lessons = int(
        (
            await db.execute(
                select(func.count(Lesson.id))
                .join(Module, Module.id == Lesson.module_id)
                .where(Module.course_id == course.id, Lesson.deleted_at.is_(None))
            )
        ).scalar_one()
    )

    avg_progress = 0.0
    if total_lessons and enrollments:
        completed_per_enrollment = await db.execute(
            select(
                Enrollment.id,
                func.count(LessonProgress.id).label("done"),
            )
            .select_from(Enrollment)
            .outerjoin(
                LessonProgress,
                and_(
                    LessonProgress.enrollment_id == Enrollment.id,
                    LessonProgress.completed_at.is_not(None),
                ),
            )
            .where(Enrollment.course_id == course.id)
            .group_by(Enrollment.id)
        )
        ratios = [float(done) / total_lessons for _, done in completed_per_enrollment.all()]
        avg_progress = round(sum(ratios) / len(ratios) * 100.0, 1) if ratios else 0.0

    enrollments_7 = int(
        (
            await db.execute(
                select(func.count(Enrollment.id)).where(
                    Enrollment.course_id == course.id, Enrollment.created_at >= seven
                )
            )
        ).scalar_one()
    )
    enrollments_30 = int(
        (
            await db.execute(
                select(func.count(Enrollment.id)).where(
                    Enrollment.course_id == course.id, Enrollment.created_at >= thirty
                )
            )
        ).scalar_one()
    )

    completion_rate = (completions / enrollments) if enrollments else 0.0

    return CourseAnalytics(
        course_id=course.id,
        enrollments=enrollments,
        completions=completions,
        completion_rate=round(completion_rate, 3),
        avg_rating=round(avg_rating, 2) if avg_rating is not None else None,
        rating_count=int(rating_count or 0),
        avg_progress_pct=avg_progress,
        enrollments_last_7d=enrollments_7,
        enrollments_last_30d=enrollments_30,
    )
