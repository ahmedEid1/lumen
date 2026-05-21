"""Enrollment, progress, certificates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.ids import new_id
from app.models.course import Course, CourseStatus, Enrollment, Lesson, LessonProgress
from app.models.notification import NotificationKind
from app.models.quiz_attempt import QuizAttempt
from app.models.user import User
from app.repositories import courses as courses_repo
from app.repositories import notifications as notifications_repo


async def enroll(db: AsyncSession, *, user: User, course: Course) -> Enrollment:
    if course.status != CourseStatus.published:
        raise ForbiddenError("Course is not available", code="enrollment.not_available")
    existing = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if existing:
        return existing
    enrollment = Enrollment(user_id=user.id, course_id=course.id)
    db.add(enrollment)
    await db.flush()
    await notifications_repo.create(
        db,
        user_id=user.id,
        kind=NotificationKind.enrolled,
        title=f"Welcome to {course.title}!",
        body="You're all set. Open your dashboard to start learning.",
        data={"course_id": course.id},
    )
    return enrollment


async def unenroll(db: AsyncSession, *, user: User, course: Course) -> None:
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if not enrollment:
        return
    # A completed enrollment owns the learner's certificate_id and all of
    # their lesson_progress. Deleting it cascades through both, so the
    # cert becomes unverifiable (/verify/{certificate_id} → 404) and the
    # achievement record is silently destroyed. Treat completed
    # enrollments as a permanent transcript entry; unenroll is for
    # mid-progress course abandonment, not for retracting credentials.
    if enrollment.completed_at is not None:
        raise ConflictError(
            "Cannot unenroll from a completed course — your certificate"
            " would no longer verify. Contact support if you need this"
            " record removed.",
            code="enrollment.completed",
        )
    await db.delete(enrollment)


async def record_quiz_attempt(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    score: int,
    passed: bool,
    payload: dict[str, Any] | None = None,
) -> tuple[Enrollment, LessonProgress, float]:
    """Persist a quiz attempt.

    Unlike :func:`mark_lesson`, a failing retake never clears a previously
    earned ``completed_at`` — once a learner has passed a quiz, the lesson
    stays complete regardless of subsequent attempts. The latest score is
    always stored on ``LessonProgress.score``.
    """
    mod = await courses_repo.get_module(db, lesson.module_id)
    if mod is None:
        raise NotFoundError("Module not found", code="module.not_found")
    course = await courses_repo.get_course(db, mod.course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if not enrollment:
        raise ForbiddenError("Not enrolled", code="enrollment.required")

    lp = await courses_repo.get_or_create_progress(db, enrollment_id=enrollment.id, lesson_id=lesson.id)
    lp.score = max(0, min(100, score))
    if payload:
        lp.payload = {**(lp.payload or {}), **payload}
    if passed:
        await courses_repo.mark_completed(db, lp, payload=None)

    # Append-only attempt history (iter 73). Captures the verbatim
    # answers so a future "review your attempt" UI can highlight
    # which questions were missed; persists even if the lesson is
    # later soft-deleted (FK cascades only on hard-delete).
    attempt = QuizAttempt(
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        score=max(0, min(100, score)),
        passed=passed,
        answers=(payload or {}).get("answers", {}),
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    await db.flush()

    total = await courses_repo.count_lessons_in_course(db, course.id)
    done = await courses_repo.count_completed_lessons(db, enrollment.id)
    pct = (done / total * 100.0) if total else 0.0

    if total and done == total and not enrollment.completed_at:
        enrollment.completed_at = datetime.now(timezone.utc)
        enrollment.certificate_id = f"cert_{new_id()}"
        await notifications_repo.create(
            db,
            user_id=user.id,
            kind=NotificationKind.certificate_ready,
            title=f"Certificate ready: {course.title}",
            body="Congratulations on completing the course!",
            data={"course_id": course.id, "certificate_id": enrollment.certificate_id},
        )

    return enrollment, lp, pct


async def mark_lesson(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    completed: bool,
    payload: dict[str, Any] | None = None,
) -> tuple[Enrollment, LessonProgress, float]:
    mod = await courses_repo.get_module(db, lesson.module_id)
    if mod is None:
        raise NotFoundError("Module not found", code="module.not_found")
    course = await courses_repo.get_course(db, mod.course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    enrollment = await courses_repo.get_enrollment(db, user_id=user.id, course_id=course.id)
    if not enrollment:
        raise ForbiddenError("Not enrolled", code="enrollment.required")

    lp = await courses_repo.get_or_create_progress(db, enrollment_id=enrollment.id, lesson_id=lesson.id)
    if completed:
        await courses_repo.mark_completed(db, lp, payload=payload)
    else:
        lp.completed_at = None

    total = await courses_repo.count_lessons_in_course(db, course.id)
    done = await courses_repo.count_completed_lessons(db, enrollment.id)
    pct = (done / total * 100.0) if total else 0.0

    if total and done == total and not enrollment.completed_at:
        enrollment.completed_at = datetime.now(timezone.utc)
        enrollment.certificate_id = f"cert_{new_id()}"
        await notifications_repo.create(
            db,
            user_id=user.id,
            kind=NotificationKind.certificate_ready,
            title=f"Certificate ready: {course.title}",
            body="Congratulations on completing the course!",
            data={"course_id": course.id, "certificate_id": enrollment.certificate_id},
        )

    return enrollment, lp, pct


async def progress_pct(db: AsyncSession, *, enrollment: Enrollment) -> float:
    total = await courses_repo.count_lessons_in_course(db, enrollment.course_id)
    if not total:
        return 0.0
    done = await courses_repo.count_completed_lessons(db, enrollment.id)
    return round(done / total * 100.0, 1)
