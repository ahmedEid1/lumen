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

from app.api.deps import CurrentUser, DBSession, RequireInstructor
from app.core.errors import ForbiddenError, NotFoundError
from app.core.ratelimit import limiter
from app.models.course import Course
from app.repositories import courses as courses_repo
from app.schemas.course import QuizQuestion
from app.services import ai_authoring, authoring_orchestrator

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


# ---------- Phase I3: self-critique authoring loop ----------


class DraftCourseRequest(BaseModel):
    """Body for ``POST /studio/ai/draft-course``.

    ``brief`` is the same one-paragraph free-form description the
    single-shot ``/ai/outline`` endpoint accepts. ``subject_slug``
    resolves to a real :class:`Subject` row up-front — we can't
    create one on behalf of the instructor here, so a missing slug
    is a 404 the UI surfaces as "pick a subject before drafting."
    """

    brief: str = Field(min_length=1, max_length=4_000)
    subject_slug: str = Field(min_length=1, max_length=220)


class CriticScoresOut(BaseModel):
    """Three-axis score block — mirrors :class:`CriticScores`."""

    coverage: int
    learning_arc: int
    scope: int
    mean: float


class DraftCourseResponse(BaseModel):
    """Full output of one self-critique authoring run.

    Renders as the success payload the studio modal needs to deep-
    link the instructor into ``/studio/draft/{course_id}`` for the
    reasoning trace.
    """

    course_id: str
    slug: str
    module_count: int
    lesson_count: int
    final_score: CriticScoresOut
    final_rationale: str
    draft_id: str
    revisions_used: int


class DraftTraceStepOut(BaseModel):
    """One step in the rendered reasoning timeline."""

    id: str
    draft_id: str
    course_id: str | None
    step: str
    step_index: int
    status: str
    duration_ms: int
    payload: dict[str, object]
    created_at: str


class DraftTraceResponse(BaseModel):
    """Full critique-revise chain for one course's most-recent draft."""

    course_id: str
    draft_id: str | None
    steps: list[DraftTraceStepOut]


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


# ---------- Phase I3 endpoints ----------


@router.post(
    "/ai/draft-course",
    response_model=DraftCourseResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def draft_course(
    payload: DraftCourseRequest,
    user: RequireInstructor,
    db: DBSession,
    request: Request,
    response: Response,
) -> DraftCourseResponse:
    """Run the self-critique authoring loop end-to-end (Lumen v2 I3).

    Orchestrates researcher → outliner → critic ↺ reviser →
    lesson-drafter → final-critic. Persists a draft course +
    modules + lessons AND the full ``course_draft_traces`` chain.
    Returns the final critic's score so the studio surface can
    render the publish-anyway button with an honest signal.

    Shares the existing ``/ai/*`` 5/minute per-user rate limit —
    one full draft burns up to ``6 + 2 × N_lessons + 1`` LLM calls,
    so 5/minute is already extremely generous; we don't add a
    separate tighter limit.
    """
    result = await authoring_orchestrator.draft_course(
        db,
        user=user,
        brief=payload.brief,
        subject_slug=payload.subject_slug,
    )
    return DraftCourseResponse(
        course_id=result.course_id,
        slug=result.slug,
        module_count=result.module_count,
        lesson_count=result.lesson_count,
        final_score=CriticScoresOut(
            coverage=result.final_score.coverage,
            learning_arc=result.final_score.learning_arc,
            scope=result.final_score.scope,
            mean=round(result.final_score.mean, 2),
        ),
        final_rationale=result.final_rationale,
        draft_id=result.draft_id,
        revisions_used=result.revisions_used,
    )


@router.get(
    "/drafts/{course_id}/trace",
    response_model=DraftTraceResponse,
)
async def get_draft_trace(
    course_id: str,
    user: CurrentUser,
    db: DBSession,
) -> DraftTraceResponse:
    """Return the full critique-revise trace for ``course_id``'s draft.

    Authorisation: the caller must own the course OR be an admin.
    Instructors-other-than-the-owner get 403 — a trace reveals the
    course's drafting context which would leak the instructor's
    authoring approach. We surface a 404 for non-existent courses
    so we don't leak whether a private slug exists.

    Returns the rows in step-index order (the same order the
    timeline renders top-to-bottom).
    """
    course = await courses_repo.get_course(db, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course.not_found")
    if not (user.is_admin() or course.owner_id == user.id):
        raise ForbiddenError("Not your course", code="course.forbidden")

    rows = await authoring_orchestrator.list_traces_for_course(
        db, course_id=course.id
    )
    steps = [
        DraftTraceStepOut(
            id=r.id,
            draft_id=r.draft_id,
            course_id=r.course_id,
            step=r.step,
            step_index=r.step_index,
            status=r.status,
            duration_ms=r.duration_ms,
            payload=dict(r.payload or {}),
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    draft_id = steps[0].draft_id if steps else None
    return DraftTraceResponse(
        course_id=course.id, draft_id=draft_id, steps=steps
    )
