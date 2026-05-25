"""Personalized learning-path endpoints (Lumen v2 Phase I5).

Five endpoints sit under ``/api/v1/me/learning-path``:

* ``POST   /api/v1/me/learning-path``                          — build (or rebuild) the learner's plan from a goal.
* ``GET    /api/v1/me/learning-path``                          — fetch the current active path.
* ``GET    /api/v1/me/learning-path/today``                    — bundle the "what to do today" widget data.
* ``POST   /api/v1/me/learning-path/steps/{step_id}/complete`` — flip a single step to completed.
* ``POST   /api/v1/me/learning-path/replan``                   — manual re-plan trigger (owner only).

All endpoints scope strictly to the calling learner — there's no
shape that lets an instructor or admin view another learner's path
on this surface (the future admin observability page reads
``agent_traces`` directly when it needs that view).

Rate limiting:
* Build / replan are bounded at 6/hour per identity — they each
  cost a metered LLM call, so the budget guard ultimately throttles
  them but rate-limiting earlier saves the API thread from queueing
  long requests.
* Read endpoints are bounded at 60/minute, matching the mastery
  surface convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError
from app.core.ratelimit import limiter
from app.models.learning_path import LearningPath, LearningPathStep
from app.services import learning_path as learning_path_service

router = APIRouter()


# ---------- Response shapes ----------


class LearningPathStepOut(BaseModel):
    """One step in the rendered path."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    milestone_name: str
    milestone_weeks: str
    course_id: str
    course_slug: str
    status: str


class NextActionOut(BaseModel):
    """Embedded in the path response so the surface paints in one fetch."""

    course_slug: str | None = None
    kind: str | None = None


class LearningPathOut(BaseModel):
    """Full active-path shape returned by the read + write endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    goal: str
    rationale: str
    status: str
    next_action: NextActionOut | None = None
    steps: list[LearningPathStepOut]
    created_at: datetime
    updated_at: datetime
    replanned_at: datetime


class TodayOut(BaseModel):
    """Lean "what to do today" widget payload."""

    course_slug: str | None = Field(
        default=None,
        description=(
            "The course the agent suggests engaging with today. Null when the "
            "learner has no active path or when the agent's next_action was "
            "dropped during validation."
        ),
    )
    kind: str | None = Field(
        default=None,
        description=(
            "One of ``start_lesson | review_due_cards | take_quiz`` or null "
            "when no active path exists."
        ),
    )
    lesson_id_if_applicable: str | None = Field(
        default=None,
        description=(
            "Resolved lesson id when ``kind=start_lesson`` and the service "
            "could pick a clear 'begin here' lesson — otherwise null."
        ),
    )
    due_review_count: int = Field(
        default=0,
        description="FSRS due-card count at the moment of the request.",
    )


class BuildPathIn(BaseModel):
    """Request body for the build endpoint."""

    goal: str = Field(min_length=4, max_length=2_000)


# ---------- Serializers ----------


def _next_action_out(raw: dict[str, Any] | None) -> NextActionOut | None:
    """Normalise the stored JSONB blob into the response shape."""
    if not raw:
        return None
    return NextActionOut(
        course_slug=raw.get("course_slug"),
        kind=raw.get("kind"),
    )


def _path_out(path: LearningPath) -> LearningPathOut:
    """Project an ORM row + its eagerly-loaded steps to the response."""
    steps_sorted: list[LearningPathStep] = sorted(path.steps, key=lambda s: s.position)
    return LearningPathOut(
        id=path.id,
        goal=path.goal,
        rationale=path.rationale,
        status=path.status,
        next_action=_next_action_out(path.next_action),
        steps=[
            LearningPathStepOut(
                id=s.id,
                position=s.position,
                milestone_name=s.milestone_name,
                milestone_weeks=s.milestone_weeks,
                course_id=s.course_id,
                course_slug=s.course_slug,
                status=s.status,
            )
            for s in steps_sorted
        ],
        created_at=path.created_at,
        updated_at=path.updated_at,
        replanned_at=path.replanned_at,
    )


# ---------- Endpoints ----------


@router.post(
    "/learning-path",
    response_model=LearningPathOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("6/hour")
async def build_learning_path(
    payload: BuildPathIn,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LearningPathOut:
    """Build (or rebuild) the learner's active learning path from a goal.

    Archives any previous active path. Each call hits the metered
    LLM provider and may take several seconds; the rate-limit shape
    is deliberately tight to discourage hammering the agent.
    """
    path = await learning_path_service.build_path(db, user_id=user.id, goal=payload.goal)
    return _path_out(path)


@router.get(
    "/learning-path",
    response_model=LearningPathOut,
)
@limiter.limit("60/minute")
async def get_learning_path(
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LearningPathOut:
    """Return the calling learner's active path or 404 if none exists."""
    path = await learning_path_service.get_active_path(db, user_id=user.id)
    if path is None:
        raise NotFoundError(
            "No active learning path. Build one by posting a goal.",
            code="learning_path.not_found",
        )
    return _path_out(path)


@router.get(
    "/learning-path/today",
    response_model=TodayOut,
)
@limiter.limit("60/minute")
async def get_today(
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> TodayOut:
    """Lean "what to do today" widget payload.

    Returns ``200`` with empty/null fields when the learner has no
    active path so the widget can render its own empty state without
    handling a 404.
    """
    action = await learning_path_service.get_today_action(db, user_id=user.id)
    if action is None:
        return TodayOut()
    return TodayOut(**action)


@router.post(
    "/learning-path/steps/{step_id}/complete",
    response_model=LearningPathStepOut,
)
@limiter.limit("60/minute")
async def complete_step(
    step_id: str,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LearningPathStepOut:
    """Flip a step to ``completed``. Owner-scoped, raises 404 cross-user."""
    step = await learning_path_service.mark_step_complete(db, step_id=step_id, user_id=user.id)
    return LearningPathStepOut(
        id=step.id,
        position=step.position,
        milestone_name=step.milestone_name,
        milestone_weeks=step.milestone_weeks,
        course_id=step.course_id,
        course_slug=step.course_slug,
        status=step.status,
    )


@router.post(
    "/learning-path/replan",
    response_model=LearningPathOut,
)
@limiter.limit("6/hour")
async def manual_replan(
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LearningPathOut:
    """Manually trigger a re-plan against the learner's current active path.

    Same rate-limit shape as build because it has the same upstream
    cost. Returns the new active path on success; 404 when the
    learner has no active path to re-plan.
    """
    path = await learning_path_service.replan_for_user(db, user_id=user.id)
    if path is None:
        raise NotFoundError(
            "No active learning path to re-plan.",
            code="learning_path.not_found",
        )
    return _path_out(path)
