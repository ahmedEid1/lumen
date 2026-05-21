"""Enrollment + per-lesson progress."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.api.v1 import _builders
from app.core.errors import NotFoundError, ValidationAppError
from app.core.ratelimit import limiter
from app.models.course import LessonType
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import EnrollmentOut, ProgressUpdate
from app.services import enrollment as enrollment_service
from app.services import quiz as quiz_service

router = APIRouter()


@router.get("/enrollments", response_model=list[EnrollmentOut])
async def list_my_enrollments(user: CurrentUser, db: DBSession) -> list[EnrollmentOut]:
    enrollments = await courses_repo.list_enrollments_for_user(db, user.id)
    stats = await courses_repo.stats_for_courses(db, [e.course_id for e in enrollments])
    out: list[EnrollmentOut] = []
    for e in enrollments:
        pct = await enrollment_service.progress_pct(db, enrollment=e)
        out.append(
            EnrollmentOut(
                id=e.id,
                created_at=e.created_at,
                completed_at=e.completed_at,
                certificate_id=e.certificate_id,
                progress_pct=pct,
                course=_builders.list_item(e.course, stats.get(e.course_id, {})),
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
        course=_builders.list_item(course, stats),
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
    if not lesson or lesson.deleted_at is not None:
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


# ---------- Quiz submission ----------


class QuizSubmitRequest(BaseModel):
    """Map of question id → answer.

    Choice questions take a list of choice ids; short-answer questions take a
    string.
    """

    answers: dict[str, Any] = Field(default_factory=dict, max_length=100)


class QuizQuestionResultOut(BaseModel):
    question_id: str
    correct: bool


class QuizSubmitResponse(BaseModel):
    lesson_id: str
    score: int
    pass_score: int
    passed: bool
    correct_count: int
    total: int
    results: list[QuizQuestionResultOut]
    progress_pct: float
    completed_at: str | None = None
    certificate_id: str | None = None


class QuizAttemptOut(BaseModel):
    """One entry in the learner's quiz attempt history."""

    id: str
    score: int
    passed: bool
    submitted_at: str


@router.get(
    "/progress/lessons/{lesson_id}/quiz/attempts",
    response_model=list[QuizAttemptOut],
)
async def list_my_quiz_attempts(
    lesson_id: str, user: CurrentUser, db: DBSession
) -> list[QuizAttemptOut]:
    """List the calling user's attempts on a quiz lesson, newest first.

    Capped at 50 entries — a learner who's taken a quiz 50+ times is
    using it as study material; older attempts are pruneable via a
    future retention job. Returns 404 if they were never enrolled
    (the join filters by enrollment_id implicitly).
    """
    from sqlalchemy import desc, select

    from app.models.quiz_attempt import QuizAttempt

    lesson = await courses_repo.get_lesson(db, lesson_id)
    if not lesson or lesson.deleted_at is not None:
        raise NotFoundError("Lesson not found", code="lesson.not_found")
    mod = await courses_repo.get_module(db, lesson.module_id)
    if not mod:
        raise NotFoundError("Module not found", code="module.not_found")
    enrollment = await courses_repo.get_enrollment(
        db, user_id=user.id, course_id=mod.course_id
    )
    if not enrollment:
        return []
    rows = (
        await db.execute(
            select(QuizAttempt)
            .where(
                QuizAttempt.enrollment_id == enrollment.id,
                QuizAttempt.lesson_id == lesson_id,
            )
            .order_by(desc(QuizAttempt.created_at))
            .limit(50)
        )
    ).scalars().all()
    return [
        QuizAttemptOut(
            id=a.id,
            score=a.score,
            passed=a.passed,
            submitted_at=a.submitted_at.isoformat(),
        )
        for a in rows
    ]


@router.post("/progress/lessons/{lesson_id}/quiz", response_model=QuizSubmitResponse)
@limiter.limit("20/minute")
async def submit_quiz(
    lesson_id: str,
    payload: QuizSubmitRequest,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> QuizSubmitResponse:
    """Server-graded quiz submission.

    The client may grade locally for instant feedback, but this endpoint is
    the authoritative source of the score that gets persisted on
    ``LessonProgress``. Passing the quiz also marks the lesson complete.

    Rate-limited (20/minute) because grading walks the full question list
    and writes to LessonProgress — without a cap a learner could replay
    a 50-question quiz in a tight loop and burn CPU + DB writes.
    """
    lesson = await courses_repo.get_lesson(db, lesson_id)
    if not lesson or lesson.deleted_at is not None:
        raise NotFoundError("Lesson not found", code="lesson.not_found")
    if lesson.type != LessonType.quiz:
        raise ValidationAppError("Lesson is not a quiz", code="quiz.not_a_quiz")

    result = quiz_service.grade(lesson.data or {}, payload.answers)

    enrollment, lp, pct = await enrollment_service.record_quiz_attempt(
        db,
        user=user,
        lesson=lesson,
        score=result.score,
        passed=result.passed,
        payload={
            "answers": payload.answers,
            "score": result.score,
            "passed": result.passed,
        },
    )

    return QuizSubmitResponse(
        lesson_id=lesson.id,
        score=result.score,
        pass_score=result.pass_score,
        passed=result.passed,
        correct_count=result.correct_count,
        total=result.total,
        results=[
            QuizQuestionResultOut(question_id=r.question_id, correct=r.correct)
            for r in result.results
        ],
        progress_pct=pct,
        completed_at=lp.completed_at.isoformat() if lp.completed_at else None,
        certificate_id=enrollment.certificate_id,
    )
