"""TutorConversation + TutorMessage — course-scoped RAG tutor history.

Rebuild Phase E1. Two append-only tables that persist every back-and-
forth between a learner and the course tutor:

* :class:`TutorConversation` — one row per "ask the tutor" session.
  Scoped to ``(user_id, course_id)`` so a learner picks up where
  they left off when they reopen the panel. We deliberately don't
  share conversations across courses — the tutor is course-scoped
  by design, and mixing transcripts across courses would defeat
  the citation invariant ("every claim ties back to a lesson in
  *this* course").

* :class:`TutorMessage` — one row per turn. ``role`` is the
  OpenAI-shape literal (``user`` | ``assistant``) and ``citations``
  is the structured citation list the service layer extracted from
  the model's reply. The citation list is stored as JSONB rather
  than a normalised side table because (a) it's read alongside the
  message in 100% of cases and (b) the citation row count per
  message is small (≤ ``top_k`` from retrieval — currently 5).
  A side table would burn 1 + N round trips for what fits trivially
  in one column.

Why no soft-delete on either table: a conversation is a learner's
private artefact, like an email thread. When the owner deletes a
conversation we hard-delete the row and cascade-drop its messages —
there's no second-order viewer, no compliance reason to retain
chat logs, and a soft-delete bit would complicate the
``(user, course, last_message_at)`` listing index.

The ``ix_tutor_conversations_user_course_last`` index serves the
"my recent conversations for this course" view that the tutor
panel opens with — it's a descending composite that turns the
list-query into a straightforward index range scan.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


class TutorMessageRole(StrEnum):
    """Restricted ``user`` | ``assistant`` — no ``system`` role here.

    System prompts live in :func:`app.services.tutor.build_system_prompt`
    and are rebuilt fresh on every turn from the latest retrieval
    snapshot — we never persist them. Persisting a stale system
    prompt would create a divergence between what was sent to the
    model and what the audit log shows for the assistant turn.
    """

    user = "user"
    assistant = "assistant"


class TutorConversation(IdMixin, Base):
    """One tutor chat session for a (user, course) pair."""

    __tablename__ = "tutor_conversations"
    __table_args__ = (
        # Hot path: ``GET /api/v1/courses/{id}/tutor/conversations``
        # lists my conversations for this course, newest-touched first.
        # The descending sort key makes the panel's open-screen one
        # bounded index-only scan.
        Index(
            "ix_tutor_conversations_user_course_last",
            "user_id",
            "course_id",
            "last_message_at",
        ),
        Index("ix_tutor_conversations_course_id", "course_id"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Touched on every persisted assistant message so the panel can
    # sort recents without scanning the messages table. Identical to
    # ``created_at`` at insert time; the service layer bumps it.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship()
    course: Mapped[Course] = relationship()
    messages: Mapped[list[TutorMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="TutorMessage.created_at",
    )


class TutorMessage(IdMixin, Base):
    """One turn in a tutor conversation."""

    __tablename__ = "tutor_messages"
    __table_args__ = (
        Index(
            "ix_tutor_messages_conv_created",
            "conversation_id",
            "created_at",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[TutorMessageRole] = mapped_column(
        String(16), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # List of ``{lesson_id, lesson_title, chunk_excerpt}`` dicts —
    # always ``[]`` on user-role messages, populated on assistant
    # turns. JSONB rather than ARRAY-of-composite so adding new
    # citation fields later doesn't require a migration. The shape
    # is validated through the :class:`~app.schemas` DTOs at the
    # API edge — the column itself is intentionally loose.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]", default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[TutorConversation] = relationship(
        back_populates="messages"
    )


__all__ = [
    "TutorConversation",
    "TutorMessage",
    "TutorMessageRole",
]
