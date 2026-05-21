"""Per-course analytics for instructors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
            # Same soft-delete guard as the cohort query — completions for
            # removed lessons must not skew the average.
            .outerjoin(Lesson, Lesson.id == LessonProgress.lesson_id)
            .where(
                Enrollment.course_id == course.id,
                (LessonProgress.id.is_(None)) | (Lesson.deleted_at.is_(None)),
            )
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


@dataclass(slots=True)
class CohortRow:
    user_id: str
    full_name: str
    avatar_url: str | None
    enrolled_at: datetime
    completed_at: datetime | None
    progress_pct: float
    certificate_id: str | None


async def cohort_for_course(db: AsyncSession, *, course_id: str, viewer: User) -> list[CohortRow]:
    """Return the enrolled cohort for the given course with progress.

    Visible to the course owner and to admins. The list is ordered by
    enrolment time (newest first) and capped at 500 rows; bigger cohorts
    can be paginated in a follow-up.
    """
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    if not (viewer.is_admin() or course.owner_id == viewer.id):
        raise ForbiddenError("Not your course", code="cohort.forbidden")

    total_lessons = int(
        (
            await db.execute(
                select(func.count(Lesson.id))
                .join(Module, Module.id == Lesson.module_id)
                .where(Module.course_id == course.id, Lesson.deleted_at.is_(None))
            )
        ).scalar_one()
    )

    rows = (
        await db.execute(
            select(
                Enrollment,
                func.count(LessonProgress.id).label("done"),
            )
            .options(selectinload(Enrollment.user))
            .outerjoin(
                LessonProgress,
                and_(
                    LessonProgress.enrollment_id == Enrollment.id,
                    LessonProgress.completed_at.is_not(None),
                ),
            )
            # Don't count completions for lessons that have been soft-deleted
            # — otherwise pct can exceed 100% when curriculum shrinks.
            .outerjoin(Lesson, Lesson.id == LessonProgress.lesson_id)
            .where(
                Enrollment.course_id == course.id,
                (LessonProgress.id.is_(None)) | (Lesson.deleted_at.is_(None)),
            )
            .group_by(Enrollment.id)
            .order_by(Enrollment.created_at.desc())
            .limit(500)
        )
    ).all()

    out: list[CohortRow] = []
    for enrollment, done in rows:
        pct = round((float(done) / total_lessons) * 100.0, 1) if total_lessons else 0.0
        u = enrollment.user
        out.append(
            CohortRow(
                user_id=u.id,
                full_name=u.full_name,
                avatar_url=u.avatar_url,
                enrolled_at=enrollment.created_at,
                completed_at=enrollment.completed_at,
                progress_pct=pct,
                certificate_id=enrollment.certificate_id,
            )
        )
    return out
