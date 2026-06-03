"""Append-only course-moderation audit table (ADR-0026 §"Data model changes").

``moderation_events`` is **separate from any visibility column** and is
**never dropped by the visibility down-migration** (R-C2/R-M9) — it survives a
column rollback so a re-up backfill can ask "did this course ever have a
reject/delist event?". Every moderation transition (share, resubmit, approve,
reject, delist, relist, remove) appends one row; the row is the durable history
the R-M9 re-approval rule reads.

The ``severe_abuse`` tutor-disable signal (owner keeps view/edit) reads the
latest row's ``reason_code`` (ADR-0026 §3 / DR-18-R2). The csam/illegal
full-quarantine path is the ``courses.quarantined`` column (DR-18-R2, S2.10),
NOT a JOIN against this table — that keeps the legally-sensitive case
single-source-of-truth in SQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


class ModerationEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "moderation_events"
    __table_args__ = (
        Index("ix_moderation_events_course_id_created_at", "course_id", "created_at"),
    )

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL (not CASCADE): the audit row outlives the actor's account so a
    # deleted admin doesn't erase moderation history (R-C2 append-only intent).
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    from_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    # Taxonomy: csam | illegal | severe_abuse | spam | ... (length-capped).
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Length-capped, rendered as inert text in the admin UI (FR-MOD-13).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Advisory classifier output (never a security boundary, R-C1′).
    classifier_signal: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    course: Mapped[Course] = relationship()
    actor: Mapped[User | None] = relationship()
