"""Per-learner spaced-repetition card (FSRS-6 state).

Each :class:`ReviewCard` is the persisted footprint of an FSRS-6
flashcard for a specific (user, lesson) pair — *not* a per-question
or per-attempt row. The pair is `(user_id, lesson_id)`, enforced by a
unique constraint so :func:`ensure_card` is idempotent and a single
quiz lesson can never accumulate duplicate cards for the same learner.

Cardinality choice (quiz-only for v1):

* A learner who completes a quiz lesson — pass or fail — gets exactly
  one card representing "do you still remember this quiz?". The next
  time the card comes due they re-take the same quiz; the rating they
  give themselves (Again/Hard/Good/Easy) feeds back into FSRS-6 which
  updates ``stability`` + ``difficulty`` + ``due_at``.

* We deliberately don't shard one card per question. FSRS treats each
  card as a single forgetting curve; per-question cards would explode
  the queue (5-question quiz ⇒ 5 cards/learner) and force us to render
  bare question fragments out of context. Quiz-level granularity keeps
  the surface inspectable ("review this lesson") and respects the
  lesson author's intended scope.

State columns mirror the FSRS-6 reference implementation
(``stability``, ``difficulty``, ``state``, ``due_at``,
``last_reviewed_at``); we never compute next-due locally — the
:mod:`app.services.fsrs` module delegates to the ``fsrs`` package
which is the canonical scheduler. ``total_reviews`` is a denormalized
counter for the stats endpoint so we don't have to maintain a separate
ReviewLog table (we could later — for now the count is enough).

Rebuild Phase E4.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Lesson
    from app.models.user import User


class ReviewCardState(StrEnum):
    """Mirrors FSRS' ``State`` enum (Learning / Review / Relearning).

    ``new`` is an internal pre-FSRS state — a card that has been
    created (via :func:`ensure_card`) but never reviewed. The FSRS
    library would treat such a card as Learning step 0; we keep the
    distinction so the stats endpoint can answer "how many cards
    haven't I touched yet?" without inspecting ``last_reviewed_at``.
    """

    new = "new"
    learning = "learning"
    review = "review"
    relearning = "relearning"


class ReviewCard(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_cards"
    __table_args__ = (
        # One card per (user, lesson). :func:`ensure_card` relies on this
        # to be safely idempotent across concurrent quiz submissions.
        UniqueConstraint("user_id", "lesson_id", name="uq_review_cards_user_lesson"),
        # Hot path: GET /me/reviews/queue does
        # `WHERE user_id = :u AND due_at <= now() ORDER BY due_at`.
        Index("ix_review_cards_user_due", "user_id", "due_at"),
        Index("ix_review_cards_lesson_id", "lesson_id"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )

    # FSRS-6 memory state. ``stability`` (days until retrievability
    # decays to ``desired_retention``, ~0.9) and ``difficulty`` (1.0-10.0,
    # how hard the card is) are the two parameters the algorithm
    # updates on every review. Stored as Float — FSRS' reference impl
    # uses Python floats and never asks for more precision than that.
    stability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    state: Mapped[ReviewCardState] = mapped_column(
        String(16), nullable=False, default=ReviewCardState.new
    )
    # Learning-step counter used by FSRS while the card is in the
    # Learning / Relearning states (None once it graduates to Review).
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship()
    lesson: Mapped[Lesson] = relationship()
