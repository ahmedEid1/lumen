"""Idempotency-key store (ADR-0028 §"New model: IdempotencyKey").

Clone is the first endpoint to honor ``Idempotency-Key`` (ADR-0028 §Consequences),
seeding this infrastructure for the rest of v1. A row records that a given
``(user_id, idempotency_key)`` pair already produced a durable result; a replay
with the same key returns the prior ``response_target_id`` instead of re-running
the mutation. ``expires_at`` bounds the replay window (24h for clone); a periodic
sweep reclaims expired rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class IdempotencyKey(IdMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_idem_user_key"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: The client-supplied opaque key, scoped per user.
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Logical operation the key guards, e.g. ``"course.clone"``.
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)
    #: The id of the durable result (the cloned course) a replay returns. Null
    #: only in the narrow window before the result row commits.
    response_target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Replay window upper bound; rows past this are sweepable.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
