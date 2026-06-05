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

from fastapi import APIRouter, Request, Response

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
from app.services import byok as byok_service
from app.services import learning_brief as brief_service

router = APIRouter()


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
