"""tutor_turn_jobs — L21-Sec scaffolding for L21a/b streaming.

One row per tutor turn. The Celery task that runs the orchestration
owns this row's lifecycle:

- POST handler inserts (status='pending', reserved_cost_usd + reservation_ip_key set).
- Celery task atomically promotes pending → running via the phase
  fence in ADR-0019.
- Streaming layer may flip running → streaming for clarity.
- Final state is one of: complete (turn ended cleanly), failed
  (orchestration error), aborted (user cancelled).
- Sweep beat job (running every 10-30 s) marks running rows whose
  updated_at is >60s old as failed and releases their reserved_cost.

L21-Sec ships the table empty. No producer yet. The sweep job runs
harmlessly against an empty set; the row insert lands in L21a.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION  # noqa: F401  (future use)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


# String enum kept in Python (vs PG enum) so we can extend it without
# a migration. The Alembic migration that creates the table also
# encodes these states via a default ('pending') and the partial
# index over (pending, running, streaming).
TURN_STATUS_PENDING = "pending"
TURN_STATUS_RUNNING = "running"
TURN_STATUS_STREAMING = "streaming"
TURN_STATUS_COMPLETE = "complete"
TURN_STATUS_FAILED = "failed"
TURN_STATUS_ABORTED = "aborted"

TERMINAL_TURN_STATUSES = frozenset({TURN_STATUS_COMPLETE, TURN_STATUS_FAILED, TURN_STATUS_ABORTED})


class TutorTurnJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "tutor_turn_jobs"
    __table_args__ = (
        Index(
            "ix_tutor_turn_jobs_active_updated",
            "status",
            "updated_at",
            postgresql_where=text("status IN ('pending', 'running', 'streaming')"),
        ),
        Index(
            "ix_tutor_turn_jobs_user_created",
            "user_id",
            text("created_at DESC"),
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(24), nullable=True)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default=TURN_STATUS_PENDING)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Hashed digest of the prompt-template content at the time this
    # turn was enqueued. Lets the L25 eval suite stamp every result
    # with a comparable cross-run key (plan-v7 §V6-F12).
    prompt_template_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Reservation metadata — set at POST time, released at sweep /
    # turn-complete time. The IP key is whatever bucket the per-IP
    # cap script keyed off; storing it lets the sweep release the
    # right bucket without re-deriving the key from request state.
    reserved_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=6), nullable=False, default=Decimal("0")
    )
    reservation_ip_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    user: Mapped[User] = relationship()


__all__ = [
    "TERMINAL_TURN_STATUSES",
    "TURN_STATUS_ABORTED",
    "TURN_STATUS_COMPLETE",
    "TURN_STATUS_FAILED",
    "TURN_STATUS_PENDING",
    "TURN_STATUS_RUNNING",
    "TURN_STATUS_STREAMING",
    "TutorTurnJob",
]
