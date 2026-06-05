"""Goal-intake (define) endpoints — the learner-facing build entry.

S3.4 / FR-DEFINE-01/02/03/06/09 / FR-QUOTA-04. The REST surface over the
elicitation service (``services/learning_brief``): start a bounded
clarification conversation, advance it turn-by-turn, and finalize into an
immutable :class:`BriefOut`.

Mounted under ``/api/v1/ai`` (sibling of the ``/studio/ai/*`` authoring routes,
NOT ``/studio``) because define is learner-facing (FR-DEFINE-09). Every handler
is ``RequireAuthor`` (the default capability for any active user; suspended →
denied, anonymous → 401), rate-limited on the LLM-bearing start/turn endpoints
(FR-QUOTA-04), and metered through ``call_logged`` inside the service. The
foreground :class:`LLMContext` is resolved here (API-side) and threaded down so
the call is BYOK-eligible (ADR-0027 §4 / DR-8).

Errors use the standard ``{error:{code,message,details,request_id}}`` envelope
via ``AppError`` subclasses; a cross-user/unknown session surfaces as 404
(existence-hide).
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DBSession, RequireAuthor
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.ratelimit import limiter
from app.schemas.learning_brief import (
    BriefFinalizeRequest,
    BriefOut,
    GoalStartRequest,
    GoalTurnRequest,
    GoalTurnResponse,
)
from app.services import build as build_service
from app.services import byok as byok_service
from app.services import learning_brief as brief_service

router = APIRouter()


class DraftFromBriefRequest(BaseModel):
    """Body for ``POST /ai/courses/draft`` — build a course from a finalized brief."""

    model_config = ConfigDict(extra="forbid")

    brief_id: str = Field(min_length=1, max_length=64)


class DraftFromBriefResponse(BaseModel):
    """The built (or replayed) private draft course + its reasoning-trace id."""

    course_id: str
    slug: str
    module_count: int
    lesson_count: int
    draft_id: str
    revisions_used: int


def _turn_response(brief, assistant_message: str, converged: bool) -> GoalTurnResponse:
    cap = int(get_settings().define_elicitation_max_turns)
    return GoalTurnResponse(
        session_id=brief.id,
        assistant_message=assistant_message,
        accumulated_brief=brief_service.to_draft(brief),
        turns_used=brief.turns_used,
        turns_remaining=max(0, cap - brief.turns_used),
        converged=converged,
    )


@router.post("/ai/goal/start", response_model=GoalTurnResponse)
@limiter.limit("5/minute")
async def start_goal_session(
    payload: GoalStartRequest,
    user: RequireAuthor,
    db: DBSession,
    request: Request,
    response: Response,
) -> GoalTurnResponse:
    """Open a bounded goal-intake conversation (FR-DEFINE-01/02).

    Enforces the per-user session quota (R-M10) before any LLM work; encrypts
    the raw goal at rest (FR-PRIV-01); runs the first metered clarification
    turn. Returns the session id + the running brief.
    """
    ctx = await byok_service.resolve_context(db, user_id=user.id)
    brief, assistant_message = await brief_service.start_session(
        db, user=user, goal=payload.goal, ctx=ctx
    )
    converged = brief_service.is_converged(brief)
    return _turn_response(brief, assistant_message, converged)


@router.post("/ai/goal/{session_id}/turn", response_model=GoalTurnResponse)
@limiter.limit("10/minute")
async def take_goal_turn(
    session_id: str,
    payload: GoalTurnRequest,
    user: RequireAuthor,
    db: DBSession,
    request: Request,
    response: Response,
) -> GoalTurnResponse:
    """Advance the conversation by one learner reply (FR-DEFINE-02/08).

    At the turn cap returns 429 ``define.turn_cap`` (no LLM call). A finalized
    brief returns 422 ``define.brief_finalized``. An unknown/cross-user session
    returns 404 (existence-hide).
    """
    ctx = await byok_service.resolve_context(db, user_id=user.id)
    result = await brief_service.take_turn(
        db, user=user, session_id=session_id, message=payload.message, ctx=ctx
    )
    if result is None:
        raise NotFoundError("Goal session not found", code="define.session_not_found")
    brief, assistant_message, converged = result
    return _turn_response(brief, assistant_message, converged)


@router.post("/ai/goal/{session_id}/finalize", response_model=BriefOut)
async def finalize_goal_session(
    session_id: str,
    payload: BriefFinalizeRequest,
    user: RequireAuthor,
    db: DBSession,
) -> BriefOut:
    """Freeze the brief into an immutable :class:`BriefOut` (FR-DEFINE-03, UC-3).

    Applies optional ``edits`` once. A second finalize returns 422
    ``define.brief_finalized``; an unknown/cross-user session returns 404. No
    LLM call → no rate limit needed here.
    """
    brief = await brief_service.finalize(db, user=user, session_id=session_id, edits=payload.edits)
    if brief is None:
        raise NotFoundError("Goal session not found", code="define.session_not_found")
    return BriefOut.model_validate(brief)


@router.post(
    "/ai/courses/draft",
    response_model=DraftFromBriefResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def build_course_from_brief(
    payload: DraftFromBriefRequest,
    user: RequireAuthor,
    db: DBSession,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DraftFromBriefResponse:
    """Build a PRIVATE draft course from a finalized brief (FR-DEFINE-05/11/13/15).

    The canonical self-serve build entry (learner-facing, NOT ``/studio``). The
    foreground :class:`LLMContext` is resolved here so the metered pipeline is
    BYOK-eligible (ADR-0027 §4 / DR-8). The build service enforces idempotency
    (a finalized brief that already produced a live course replays it), the
    per-user concurrency cap (``define.build_in_flight`` 409), and the non-dollar
    daily quota (``define.build_quota`` 429). On unrecoverable pipeline failure the
    course is left ``build_failed`` and a normalized ``define.build_failed`` 502 is
    returned. ``Idempotency-Key`` is accepted (the brief id is the primary
    idempotency key in v1; the header is reserved for the S4 idempotency table).
    The slowapi cap is the fast first line; the DB advisory-lock/COUNT are durable.
    """
    _ = idempotency_key  # reserved (brief_id is the v1 idempotency key)
    ctx = await byok_service.resolve_context(db, user_id=user.id)
    result = await build_service.build_from_brief(db, user=user, brief_id=payload.brief_id, ctx=ctx)
    return DraftFromBriefResponse(
        course_id=result.course_id,
        slug=result.slug,
        module_count=result.module_count,
        lesson_count=result.lesson_count,
        draft_id=result.draft_id,
        revisions_used=result.revisions_used,
    )
