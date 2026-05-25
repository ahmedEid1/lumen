"""Course discussion threads.

Lumen ships flat chat per course (real-time, ephemeral) and *also*
needs a structured discussion forum for long-form Q&A: "I got stuck
on lesson 5", "the answer to quiz Q3 seems wrong", "anyone want a
study buddy". Chat is wrong for this — it scrolls away and isn't
threadable; reviews are wrong because they're 1-rating-per-learner.

Two-level model: ``Discussion`` is a top-level thread (title +
body), ``DiscussionReply`` is a flat list of responses under it.
We deliberately don't nest replies — every modern Q&A forum has
learned that infinite nesting harms readability more than it helps,
and Stack-Overflow-style "answer + comments" semantics keep the
mental model simple.

Both tables soft-delete via ``deleted_at`` so moderators can hide
content without nuking the thread structure for everyone else.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


class Discussion(IdMixin, TimestampMixin, Base):
    __tablename__ = "discussions"
    __table_args__ = (Index("ix_discussions_course_created", "course_id", "created_at"),)

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    course: Mapped[Course] = relationship()
    author: Mapped[User | None] = relationship()
    replies: Mapped[list[DiscussionReply]] = relationship(
        back_populates="discussion",
        cascade="all, delete-orphan",
        order_by="DiscussionReply.created_at.asc()",
    )


class DiscussionReply(IdMixin, TimestampMixin, Base):
    __tablename__ = "discussion_replies"
    __table_args__ = (
        Index("ix_discussion_replies_discussion_created", "discussion_id", "created_at"),
    )

    discussion_id: Mapped[str] = mapped_column(
        ForeignKey("discussions.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    discussion: Mapped[Discussion] = relationship(back_populates="replies")
    author: Mapped[User | None] = relationship()
