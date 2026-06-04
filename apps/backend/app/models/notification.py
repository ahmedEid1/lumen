"""In-app notification model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class NotificationKind(StrEnum):
    enrolled = "enrolled"
    lesson_available = "lesson_available"
    certificate_ready = "certificate_ready"
    review_received = "review_received"
    chat_mention = "chat_mention"
    security = "security"
    discussion_reply = "discussion_reply"
    # Sent to the ORIGIN course owner when someone clones their publicly-listed
    # course (FR-CLONE-19 / ADR-0028 §Decision.9). Display-name only; gated by
    # the owner's notification_prefs like every other kind.
    course_cloned = "course_cloned"


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_id_created", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[NotificationKind] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the daily digest worker (:mod:`app.workers.tasks.digest`) has
    # included this row in a bundled email. Set on send so subsequent
    # runs don't double-deliver the same item.
    digested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()
