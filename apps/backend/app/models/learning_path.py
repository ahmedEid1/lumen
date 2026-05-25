"""LearningPath + LearningPathStep — the goal-to-curriculum agent's output.

Lumen v2 Phase I5. Persistence shape for the personalized learning-path
agent. A learner states a goal ("I want to be a backend engineer in
6 months"); the agent picks ~8 courses from the catalog, sequences
them under 3-5 named milestones, and writes one ``learning_paths``
row + N ``learning_path_steps`` rows.

Why two tables (not one with a JSONB blob):

1. **Stable step ids.** The frontend "mark step complete" CTA points
   at a specific step id; if steps lived inside a JSONB array they'd
   shuffle around on every re-plan. Concrete rows give us stable
   nanoid ids that the UI can deep-link to.

2. **Cascaded course updates.** Each step FKs to a real ``courses``
   row, which means a course rename / re-tagging propagates without
   us re-walking JSONB. The denormalised ``course_slug`` column is
   the URL-friendly handle the UI renders; we keep it on the step
   so a slug rotation between re-plans doesn't break the displayed
   path.

3. **Per-step status.** ``pending | in_progress | completed`` lives
   on the step. The mastery roll-up already gives us "completion %"
   per course; this is the path-specific status — a learner who
   finishes the first course on their path flips that step to
   ``completed`` without affecting other paths that might list the
   same course.

The ``status`` field on the path itself is a simple two-value tag:
``active`` (the one currently driving the dashboard) or ``archived``
(superseded by a re-plan or replaced when the learner re-states
their goal). A partial unique index in migration 0024 enforces
"only one active path per user"; archived paths pile up as history.

The ``next_action`` JSONB blob carries the agent's "what to do
today" hint — ``{course_slug, kind}`` where ``kind`` is one of
``start_lesson | review_due_cards | take_quiz``. The frontend's
TodayWidget reads this without joining anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin

if TYPE_CHECKING:
    pass


# Status literals — exported so callers don't sprinkle string literals.
PATH_STATUS_ACTIVE = "active"
PATH_STATUS_ARCHIVED = "archived"

STEP_STATUS_PENDING = "pending"
STEP_STATUS_IN_PROGRESS = "in_progress"
STEP_STATUS_COMPLETED = "completed"

# Recognised ``next_action.kind`` values. Open-ended at the column
# level (it's a JSONB blob) but the service layer constrains writes
# to these three so the frontend doesn't have to handle surprise
# kinds. Keep in sync with the system prompt's spec.
NEXT_ACTION_KIND_START_LESSON = "start_lesson"
NEXT_ACTION_KIND_REVIEW_DUE_CARDS = "review_due_cards"
NEXT_ACTION_KIND_TAKE_QUIZ = "take_quiz"


class LearningPath(IdMixin, Base):
    """One personalized learning plan — see module docstring for the full shape."""

    __tablename__ = "learning_paths"
    __table_args__ = (
        # Per-user lookup ("does this user have any path?").
        Index("ix_learning_paths_user_id", "user_id"),
        # Partial unique index — only one ``status='active'`` per user.
        # SQLAlchemy reflects this index from the table; the migration
        # is the source of truth for the partial predicate.
        Index(
            "uq_learning_paths_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form natural-language reasoning the agent emitted. The
    # frontend renders this verbatim so the learner can see "why"
    # behind each pick. Empty string until the agent fills it in.
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # ``{course_slug: str, kind: str}`` or null. The TodayWidget reads
    # this directly; the API enriches it with ``due_review_count``
    # and (for ``start_lesson``) a resolved lesson id.
    next_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # Stamped on initial build AND on every monthly re-plan; the
    # Celery beat job uses ``replanned_at < now - 30d`` to find
    # stale paths.
    replanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    steps: Mapped[list[LearningPathStep]] = relationship(
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="LearningPathStep.position",
    )


class LearningPathStep(IdMixin, Base):
    """One chosen course inside a milestone on a learning path."""

    __tablename__ = "learning_path_steps"
    __table_args__ = (
        Index("ix_learning_path_steps_path_position", "path_id", "position"),
        Index("ix_learning_path_steps_course_id", "course_id"),
    )

    path_id: Mapped[str] = mapped_column(
        ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False
    )
    # 0-based ordering within the path. The agent emits milestones
    # in order; we flatten the (milestone × course) matrix into a
    # single ascending sequence so the UI renders without extra
    # bookkeeping. Milestone groupings come from ``milestone_name``.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    milestone_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Week-range string, e.g. ``"1-4"`` or ``"13+"``. Stored verbatim
    # because the agent occasionally returns open ranges that don't
    # decompose into ``(start_week, end_week)`` integers cleanly.
    milestone_weeks: Mapped[str] = mapped_column(String(24), nullable=False)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised slug for stable URLs on the rendered path. Stays
    # in lockstep with ``courses.slug`` at write time (the service
    # writes this column from the resolved course); a later slug
    # rotation on the course doesn't propagate back here, which is
    # deliberate — the path shows what the learner saw when they
    # built it.
    course_slug: Mapped[str] = mapped_column(String(220), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    path: Mapped[LearningPath] = relationship(back_populates="steps")


__all__ = [
    "NEXT_ACTION_KIND_REVIEW_DUE_CARDS",
    "NEXT_ACTION_KIND_START_LESSON",
    "NEXT_ACTION_KIND_TAKE_QUIZ",
    "PATH_STATUS_ACTIVE",
    "PATH_STATUS_ARCHIVED",
    "STEP_STATUS_COMPLETED",
    "STEP_STATUS_IN_PROGRESS",
    "STEP_STATUS_PENDING",
    "LearningPath",
    "LearningPathStep",
]
