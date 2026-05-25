"""FSRS-6 spaced-repetition scheduling.

Thin adapter over the ``fsrs`` Python package. The package owns the
algorithm; we own the persistence (:class:`ReviewCard`) and the
mapping between its ``Card`` / ``State`` / ``Rating`` types and our
ORM columns.

Why FSRS-6 instead of rolling our own SM-2?

* SM-2 (Anki's pre-2024 default) treats every card with the same
  forgetting curve modulo an ease factor; it overshoots on early
  reviews and undershoots on lapses, so learners study items more
  often than they need to.
* FSRS fits a per-card stability + difficulty model from review logs
  and targets a configurable retention rate (default 0.9). The v6
  refresh tightened the initial-state estimates so brand-new cards
  schedule sensibly without a long warm-up.
* The `fsrs` package on PyPI is the reference implementation, used by
  Anki's official FSRS integration, Mochi, RemNote, and other 2026
  tools. Pulling it in avoids re-implementing (and re-validating) the
  scheduler ourselves.

Cardinality is one :class:`ReviewCard` per (user, lesson) — see the
model docstring for why we don't shard per question.

Rebuild Phase E4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fsrs import Card, Rating, Scheduler, State
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.course import Lesson, Module
from app.models.review_card import ReviewCard, ReviewCardState

if TYPE_CHECKING:
    pass


# A single shared :class:`Scheduler`. The class is stateless across
# reviews (its instance attributes — parameters, desired_retention,
# learning_steps — are configuration, not running state), so reusing
# one avoids re-allocating the algorithm-parameter tuple on every call.
_SCHEDULER: Scheduler | None = None


def _scheduler() -> Scheduler:
    """Lazy singleton accessor.

    Module-level instantiation would force the ``fsrs`` import at app
    boot, which is fine — but lazy is consistent with how
    :mod:`app.workers.celery_app` defers the worker init, and makes
    the module test-importable without side effects.
    """
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = Scheduler()
    return _SCHEDULER


# ---------- mapping helpers ----------


_STATE_FROM_FSRS: dict[State, ReviewCardState] = {
    State.Learning: ReviewCardState.learning,
    State.Review: ReviewCardState.review,
    State.Relearning: ReviewCardState.relearning,
}

_STATE_TO_FSRS: dict[ReviewCardState, State] = {
    # ``new`` collapses to ``Learning`` from FSRS' perspective — a
    # never-reviewed card is the same shape as a Learning step-0 card.
    ReviewCardState.new: State.Learning,
    ReviewCardState.learning: State.Learning,
    ReviewCardState.review: State.Review,
    ReviewCardState.relearning: State.Relearning,
}


_RATING_FROM_STR: dict[str, Rating] = {
    "again": Rating.Again,
    "hard": Rating.Hard,
    "good": Rating.Good,
    "easy": Rating.Easy,
}


def rating_from_str(value: str) -> Rating:
    """Translate the wire-format rating string to FSRS' enum.

    Raises :class:`ValueError` on unknown values so the API layer can
    convert to a 422 with a helpful message instead of a 500.
    """
    key = value.strip().lower()
    if key not in _RATING_FROM_STR:
        raise ValueError(f"Unknown rating: {value!r} (expected one of again, hard, good, easy)")
    return _RATING_FROM_STR[key]


def _to_fsrs_card(card: ReviewCard) -> Card:
    """Lift a persisted :class:`ReviewCard` into an FSRS :class:`Card`.

    A ``new`` card (never reviewed) has no stability/difficulty yet;
    we pass ``None`` so FSRS initializes them from its prior on the
    first review — same shape as a freshly constructed ``Card()``.
    """
    is_new = card.state == ReviewCardState.new
    return Card(
        # ``card_id`` is an int in FSRS' model; we don't round-trip our
        # nanoid through it (FSRS only uses it as an opaque tag in the
        # ReviewLog). Hash our str id to fit.
        card_id=abs(hash(card.id)) % (10**18),
        state=_STATE_TO_FSRS[card.state],
        step=card.step if card.state != ReviewCardState.review else None,
        stability=None if is_new else card.stability,
        difficulty=None if is_new else card.difficulty,
        due=card.due_at,
        last_review=card.last_reviewed_at,
    )


def _apply_fsrs(card: ReviewCard, fsrs_card: Card) -> None:
    """Write FSRS' updated card state back onto the ORM row."""
    card.stability = float(fsrs_card.stability) if fsrs_card.stability is not None else 0.0
    card.difficulty = float(fsrs_card.difficulty) if fsrs_card.difficulty is not None else 0.0
    card.state = _STATE_FROM_FSRS[fsrs_card.state]
    card.step = fsrs_card.step
    card.due_at = fsrs_card.due
    card.last_reviewed_at = fsrs_card.last_review


# ---------- public API ----------


async def ensure_card(db: AsyncSession, *, user_id: str, lesson_id: str) -> ReviewCard:
    """Idempotently get-or-create a :class:`ReviewCard` for this learner + lesson.

    Called from the quiz-submission path so every completed quiz
    lesson joins the learner's review queue. Returns the existing row
    if one already exists — preserves the learner's current FSRS state
    across re-attempts of the same quiz.

    A freshly created card is :class:`ReviewCardState.new` and due
    immediately (``due_at = now()``) so it shows up at the top of the
    queue on the next dashboard refresh.
    """
    existing = (
        await db.execute(
            select(ReviewCard).where(
                ReviewCard.user_id == user_id,
                ReviewCard.lesson_id == lesson_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    card = ReviewCard(
        user_id=user_id,
        lesson_id=lesson_id,
        stability=0.0,
        difficulty=0.0,
        state=ReviewCardState.new,
        step=0,
        due_at=now,
        last_reviewed_at=None,
        total_reviews=0,
    )
    db.add(card)
    await db.flush()
    return card


async def record_review(db: AsyncSession, *, card: ReviewCard, rating: Rating | str) -> ReviewCard:
    """Apply a rating to the given card and persist the updated state.

    Returns the same :class:`ReviewCard` instance with FSRS-updated
    fields written; the caller is responsible for the surrounding
    commit (the API layer's dependency-injected session does this).
    """
    rating_enum = rating if isinstance(rating, Rating) else rating_from_str(rating)
    fsrs_card = _to_fsrs_card(card)
    updated, _log = _scheduler().review_card(fsrs_card, rating_enum)
    _apply_fsrs(card, updated)
    card.total_reviews = (card.total_reviews or 0) + 1
    await db.flush()
    return card


async def due_cards(
    db: AsyncSession, *, user_id: str, limit: int = 20, now: datetime | None = None
) -> list[ReviewCard]:
    """List cards ready to review, oldest-due first.

    Eager-loads ``lesson.module.course`` because the queue UI renders
    course title alongside each card; without the joinedload we'd N+1
    in the API.
    """
    cutoff = now or datetime.now(UTC)
    res = await db.execute(
        select(ReviewCard)
        .options(joinedload(ReviewCard.lesson).joinedload(Lesson.module).joinedload(Module.course))
        .where(
            ReviewCard.user_id == user_id,
            ReviewCard.due_at <= cutoff,
        )
        .order_by(ReviewCard.due_at.asc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def stats(db: AsyncSession, *, user_id: str, now: datetime | None = None) -> dict[str, int]:
    """Per-bucket counters for the dashboard tile.

    Returns ``{ "due": n, "learning": n, "review": n, "next_7_days": n }``.
    ``due`` counts cards currently due (``due_at <= now``); the state
    counters count *all* of the user's cards in that state regardless
    of due-at so the learner can see their total backlog vs the active
    review pool. ``next_7_days`` is the forward-looking horizon — cards
    that will become due in the next 7 days (excluding ones already due).
    """
    cutoff = now or datetime.now(UTC)
    horizon = cutoff + timedelta(days=7)
    rows = (
        await db.execute(
            select(
                func.count().filter(ReviewCard.due_at <= cutoff).label("due"),
                func.count().filter(ReviewCard.state == ReviewCardState.learning).label("learning"),
                func.count().filter(ReviewCard.state == ReviewCardState.review).label("review"),
                func.count()
                .filter(ReviewCard.due_at > cutoff, ReviewCard.due_at <= horizon)
                .label("next_7_days"),
            ).where(ReviewCard.user_id == user_id)
        )
    ).one()
    return {
        "due": int(rows.due or 0),
        "learning": int(rows.learning or 0),
        "review": int(rows.review or 0),
        "next_7_days": int(rows.next_7_days or 0),
    }
