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

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


class ReportStatus(StrEnum):
    """Lifecycle of a user-filed course report (S6.3 / DR-20).

    ``open`` → admin hasn't acted; ``actioned`` → resolved with a moderation
    action (delist/remove); ``dismissed`` → resolved as no-action. Only ``open``
    rows participate in the partial-unique coalescing index.
    """

    open = "open"
    actioned = "actioned"
    dismissed = "dismissed"


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


class CourseReport(IdMixin, TimestampMixin, Base):
    """A user-filed report against a publicly-listed course (S6.3 / FR-MOD-11).

    Reportability routes through ``visibility.is_publicly_listed`` (never a raw
    ``status==published`` check). Eligibility is gated by DR-20 (email-verified
    AND account-age ≥ threshold) at the service layer.

    Coalescing: the partial-unique index ``uq_course_reports_open`` over
    ``(course_id, reporter_id) WHERE status='open'`` means one reporter can hold
    at most one OPEN report per course — a second report updates the existing
    open row instead of inserting a duplicate. Resolving the report (actioned /
    dismissed) frees the slot, so the same reporter could file again later.
    """

    __tablename__ = "course_reports"
    __table_args__ = (
        Index(
            "uq_course_reports_open",
            "course_id",
            "reporter_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_course_reports_status_created", "status", "created_at"),
    )

    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    reporter_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # Length-capped, inert text (sanitize_note before persist — FR-MOD-13).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ReportStatus.open.value)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SET NULL so a resolved-by admin who later deletes their account doesn't
    # erase the report (audit-style durability, like ModerationEvent.actor_id).
    resolved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    course: Mapped[Course] = relationship()
    reporter: Mapped[User] = relationship(foreign_keys=[reporter_id])
