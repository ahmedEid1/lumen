"""FSRS-6 spaced-repetition review queue.

Three endpoints, all scoped to the calling user:

* ``GET  /me/reviews/queue``     — next N cards whose ``due_at <= now()``
* ``POST /me/reviews/{id}/grade`` — record a rating, advance the schedule
* ``GET  /me/reviews/stats``     — counters for the dashboard tile

Note: nothing here lives under the ``/courses/{id}/reviews`` namespace
which already exists for course ratings (:mod:`app.api.v1.reviews`).
We mount this router under ``/me/reviews`` to keep the two scopes
disjoint — "reviews of a course" vs "your spaced-repetition queue" —
and to avoid any chance of an instructor accidentally seeing a
learner's private queue when fetching course feedback.

Rebuild Phase E4.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError, ValidationAppError
from app.models.course import Lesson, Module
from app.models.review_card import ReviewCard, ReviewCardState
from app.services import fsrs as fsrs_service

router = APIRouter()


# ---------- response shapes ----------


class ReviewCardLessonOut(BaseModel):
    """Slimmed lesson/course context for a queued card."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    course_id: str
    course_title: str
    course_slug: str


class ReviewCardOut(BaseModel):
    """One card in the queue."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    state: ReviewCardState
    stability: float
    difficulty: float
    due_at: datetime
    last_reviewed_at: datetime | None
    total_reviews: int
    lesson: ReviewCardLessonOut


class ReviewQueueOut(BaseModel):
    items: list[ReviewCardOut]


class ReviewStatsOut(BaseModel):
    """Counters for the dashboard / queue header."""

    due: int = Field(description="Cards whose due_at <= now")
    learning: int = Field(description="Cards in the Learning state (any due_at)")
    review: int = Field(description="Cards graduated to the Review state (any due_at)")
    next_7_days: int = Field(description="Cards due within the next 7 days (not yet overdue)")


class GradeRequest(BaseModel):
    rating: str = Field(
        description="One of: again, hard, good, easy (case-insensitive)",
        min_length=1,
        max_length=16,
    )


# ---------- helpers ----------


def _card_out(card: ReviewCard) -> ReviewCardOut:
    """Project a :class:`ReviewCard` ORM row into the API response shape.

    Pulls course context off ``lesson.module.course`` — the queue
    endpoint eager-loads this in a single SELECT via
    :func:`fsrs_service.due_cards` so we don't N+1 here.
    """
    lesson = card.lesson
    course = lesson.module.course
    return ReviewCardOut(
        id=card.id,
        state=card.state,
        stability=card.stability,
        difficulty=card.difficulty,
        due_at=card.due_at,
        last_reviewed_at=card.last_reviewed_at,
        total_reviews=card.total_reviews,
        lesson=ReviewCardLessonOut(
            id=lesson.id,
            title=lesson.title,
            course_id=course.id,
            course_title=course.title,
            course_slug=course.slug,
        ),
    )


async def _load_with_context(db, card_id: str) -> ReviewCard | None:
    """Fetch a card with its lesson + module + course pre-loaded."""
    res = await db.execute(
        select(ReviewCard)
        .options(joinedload(ReviewCard.lesson).joinedload(Lesson.module).joinedload(Module.course))
        .where(ReviewCard.id == card_id)
    )
    return res.scalar_one_or_none()


# ---------- endpoints ----------


@router.get("/queue", response_model=ReviewQueueOut)
async def get_queue(
    user: CurrentUser,
    db: DBSession,
    limit: int = 20,
) -> ReviewQueueOut:
    """Next N cards due for this learner, oldest-due first.

    ``limit`` is clamped to 1-100; callers asking for more should
    paginate by re-fetching after they've graded some.
    """
    capped = max(1, min(int(limit or 20), 100))
    cards = await fsrs_service.due_cards(db, user_id=user.id, limit=capped)
    return ReviewQueueOut(items=[_card_out(c) for c in cards])


@router.get("/stats", response_model=ReviewStatsOut)
async def get_stats(user: CurrentUser, db: DBSession) -> ReviewStatsOut:
    """Counters for the queue dashboard tile."""
    counts = await fsrs_service.stats(db, user_id=user.id)
    return ReviewStatsOut(**counts)


@router.post("/{card_id}/grade", response_model=ReviewCardOut, status_code=status.HTTP_200_OK)
async def grade_card(
    card_id: str,
    payload: GradeRequest,
    user: CurrentUser,
    db: DBSession,
) -> ReviewCardOut:
    """Record a rating against a card and return its updated schedule.

    422 on an unknown rating string; 404 if the card doesn't exist or
    belongs to another user (we collapse both to "not found" so the
    endpoint can't be used to probe other users' card ids).
    """
    card = await db.get(ReviewCard, card_id)
    if card is None or card.user_id != user.id:
        raise NotFoundError("Card not found", code="review_card.not_found")

    try:
        await fsrs_service.record_review(db, card=card, rating=payload.rating)
    except ValueError as e:
        raise ValidationAppError(str(e), code="review_card.invalid_rating") from e

    # Re-fetch with the joinedload so the response shape carries the
    # same lesson+course context the queue endpoint emits. The session
    # already has the row in its identity map, so this is a cheap
    # ``SELECT ... WHERE id = :id`` with eager loading.
    refreshed = await _load_with_context(db, card.id)
    if refreshed is None:  # pragma: no cover - just-updated row
        raise NotFoundError("Card not found", code="review_card.not_found")
    return _card_out(refreshed)
