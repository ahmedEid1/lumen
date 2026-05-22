"""AI-assisted course-authoring endpoints.

Rebuild Phase E2. Four endpoints, all instructor-only, all rate-
limited at 5/minute per user (LLM calls are expensive). The first
three are **read-shaped** — they generate content and return it for
the instructor to review without writing anything to the database.
Only the fourth, ``/commit-outline``, persists modules + lessons,
and even then only as drafts the instructor will refine before
publishing.

Why no auto-persist on generate. The LLM hallucinates; an
instructor who hits "Generate" and walks away should not come back
to a course full of model-authored content carrying their name. The
generate calls return a preview; the studio UI surfaces the
preview in an editable tree (rename / delete / drag-reorder); only
on explicit "Create draft course" does the outline land in the DB.
The same pattern applies to per-lesson body / quiz generation: the
endpoint returns the draft, the lesson editor pre-fills, and the
instructor saves when satisfied.

Rate limits. 5/minute matches the auth-write posture (register,
password-reset). One LLM round-trip is the most expensive thing an
authenticated user can do on the platform — cost-wise and latency-
wise — so we throttle aggressively. The keying logic
(``app.core.ratelimit._identity_key``) buckets per JWT ``sub``
when available, so two instructors on the same network don't share
a limit.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession, RequireInstructor
from app.core.errors import NotFoundError
from app.core.ratelimit import limiter
from app.models.course import Course
from app.repositories import courses as courses_repo
from app.schemas.course import QuizQuestion
from app.services import ai_authoring

router = APIRouter()


# ---------- Request / response schemas ----------


class OutlineRequest(BaseModel):
    brief: str = Field(min_length=1, max_length=4_000)
    target_modules: int = Field(default=4, ge=2, le=8)


class LessonBodyRequest(BaseModel):
    lesson_title: str = Field(min_length=1, max_length=200)
    course_context: str = Field(default="", max_length=4_000)


class QuizRequest(BaseModel):
    lesson_title: str = Field(min_length=1, max_length=200)
    course_context: str = Field(default="", max_length=4_000)
    n: int = Field(default=4, ge=1, le=10)


class LessonBodyResponse(BaseModel):
    blocks: dict[str, object]


class QuizResponse(BaseModel):
    questions: list[QuizQuestion]


class CommitOutlineRequest(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)
    outline: ai_authoring.CourseOutline


class CommittedLessonOut(BaseModel):
    id: str
    title: str
    type: str
    order: int


class CommittedModuleOut(BaseModel):
    id: str
    title: str
    order: int
    lessons: list[CommittedLessonOut]


class CommitOutlineResponse(BaseModel):
    course_id: str
    modules: list[CommittedModuleOut]


# ---------- Endpoints ----------


@router.post("/ai/outline", response_model=ai_authoring.CourseOutline)
@limiter.limit("5/minute")
async def generate_outline(
    payload: OutlineRequest,
    user: RequireInstructor,
    db: DBSession,
    request: Request,
    response: Response,
) -> ai_authoring.CourseOutline:
    """Return a proposed course outline for the instructor to review.

    Does not touch the database (modulo the cost-meter row Phase H1
    writes through ``call_logged``). The instructor edits the
    returned structure in the studio preview pane before posting it
    back to ``/ai/commit-outline``.
    """
    return await ai_authoring.generate_outline(
        brief=payload.brief,
        target_modules=payload.target_modules,
        session=db,
        user_id=user.id,
    )


@router.post("/ai/lesson-body", response_model=LessonBodyResponse)
@limiter.limit("5/minute")
async def generate_lesson_body(
    payload: LessonBodyRequest,
    user: RequireInstructor,
    db: DBSession,
    request: Request,
    response: Response,
) -> LessonBodyResponse:
    """Return a Tiptap block document to pre-fill the lesson editor.

    Does not touch the database (modulo the cost-meter row Phase H1
    writes through ``call_logged``). The studio lesson editor seeds
    the block editor with the returned doc; the instructor saves the
    lesson explicitly via ``PATCH /lessons/{id}`` from the editor.
    """
    doc = await ai_authoring.generate_lesson_body(
        lesson_title=payload.lesson_title,
        course_context=payload.course_context,
        session=db,
        user_id=user.id,
    )
    return LessonBodyResponse(blocks=doc)


@router.post("/ai/quiz", response_model=QuizResponse)
@limiter.limit("5/minute")
async def generate_quiz(
    payload: QuizRequest,
    user: RequireInstructor,
    db: DBSession,
    request: Request,
    response: Response,
) -> QuizResponse:
    """Return a list of MCQ questions to pre-fill a quiz lesson.

    Does not touch the database (modulo the cost-meter row Phase H1
    writes through ``call_logged``). The studio quiz editor seeds the
    question form with the returned items; the instructor saves the
    lesson explicitly via ``PATCH /lessons/{id}`` from the editor.
    """
    questions = await ai_authoring.generate_quiz(
        lesson_title=payload.lesson_title,
        course_context=payload.course_context,
        n=payload.n,
        session=db,
        user_id=user.id,
    )
    return QuizResponse(questions=questions)


@router.post(
    "/ai/commit-outline",
    response_model=CommitOutlineResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def commit_outline(
    payload: CommitOutlineRequest,
    user: RequireInstructor,
    db: DBSession,
    request: Request,
    response: Response,
) -> CommitOutlineResponse:
    """Persist ``payload.outline`` into ``course_id`` as draft modules + lessons.

    Authorisation: the caller must own ``course_id`` (or be an admin).
    The service layer enforces this via ``_owned_course``; we don't
    re-check here. The course remains in ``draft`` status — publishing
    is a separate explicit step.
    """
    course = await ai_authoring.commit_outline(
        db,
        course_id=payload.course_id,
        owner=user,
        outline=payload.outline,
    )
    # Re-fetch with modules + lessons so the response carries the
    # ids the client needs to navigate into the editor.
    fresh = await courses_repo.get_course(db, course.id, with_modules=True)
    if fresh is None:
        raise NotFoundError("Course not found", code="course.not_found")
    return _commit_response(fresh)


def _commit_response(course: Course) -> CommitOutlineResponse:
    """Shape a course + its modules + lessons into the response model."""
    mods: list[CommittedModuleOut] = []
    for m in sorted(course.modules, key=lambda x: x.order):
        live = [lsn for lsn in m.lessons if lsn.deleted_at is None]
        mods.append(
            CommittedModuleOut(
                id=m.id,
                title=m.title,
                order=m.order,
                lessons=[
                    CommittedLessonOut(
                        id=lsn.id,
                        title=lsn.title,
                        type=str(lsn.type),
                        order=lsn.order,
                    )
                    for lsn in sorted(live, key=lambda x: x.order)
                ],
            )
        )
    return CommitOutlineResponse(course_id=course.id, modules=mods)
