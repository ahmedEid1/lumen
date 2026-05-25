"""Quiz attempt history.

Earlier, a quiz attempt only persisted to ``LessonProgress.payload``,
which got overwritten on every retake. That meant:

* a learner couldn't see "did I get better?";
* an instructor analytics view couldn't see "how many tries did
  it take?" — only the final score;
* a researcher / auditor had no record that an attempt happened
  at all once the next attempt replaced it.

QuizAttempt is append-only: one row per submission. Indexed on
``(enrollment_id, lesson_id, created_at DESC)`` so the most
common query — "latest N attempts for this learner on this lesson"
— is a sequential read.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Enrollment, Lesson


class QuizAttempt(IdMixin, TimestampMixin, Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        Index(
            "ix_quiz_attempts_enrollment_lesson_created",
            "enrollment_id",
            "lesson_id",
            "created_at",
        ),
        Index("ix_quiz_attempts_lesson_id", "lesson_id"),
    )

    enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[str] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Verbatim graded answers so we can later show "you answered X,
    # the correct answer was Y" in an attempt-detail view.
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    enrollment: Mapped[Enrollment] = relationship()
    lesson: Mapped[Lesson] = relationship()
