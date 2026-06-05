"""``LearningBrief`` — server-owned, immutable-once-finalized goal artifact.

S3.1 / FR-DEFINE-03 / FR-PRIV-01 / DR-22. A learner's fuzzy goal is elicited
into a structured brief that drives the authoring orchestrator (S3.6). The
**raw goal text** is the only sensitive field: it is field-encrypted at rest in
``source_goal_enc`` via :mod:`app.core.secrets_crypto` (AES-256-GCM envelope),
using a key independent of the BYOK KEK migration (DR-22). The structured
fields (summary, level, outcomes, …) are non-sensitive derivations safe to
read.

**Privacy contract (FR-PRIV-01):** the plaintext goal must never appear in
``repr``/``str``/serialization/logs/admin views. The model stores only the
ciphertext bytes and ``__repr__`` deliberately omits both the plaintext and
the blob — it identifies the row by id/owner/finalized-state only. Decryption
happens at exactly one place: the in-request prompt builder in the elicitation
service / orchestrator (allowed — goal text may enter build prompts, FR-PRIV-01)
— never a cross-user RAG index.

Immutability: ``finalized_at IS NULL`` ⇒ in-progress and mutable across
elicitation turns (FR-DEFINE-08). Once ``finalize`` stamps ``finalized_at`` the
row is frozen (FR-DEFINE-03); the service enforces this, the model records it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin


class LearningBrief(IdMixin, Base):
    """A learner's elicited, structured course-build brief (private to the owner)."""

    __tablename__ = "learning_briefs"

    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Lifecycle timestamps. ``created_at`` here is explicit (not TimestampMixin)
    # because the brief has no ``updated_at`` semantics worth exposing — it is
    # either in-progress or frozen. Times are timezone-aware UTC (CLAUDE.md).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NULL while in-progress (mutable, FR-DEFINE-08); set once at finalize and
    # never cleared (immutable thereafter, FR-DEFINE-03).
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The ONLY sensitive field. Field-encrypted ciphertext blob produced by
    # ``secrets_crypto.encrypt`` (DR-22). Never logged, never serialized, never
    # in repr. BYTEA on Postgres.
    source_goal_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # ---- Structured (non-sensitive) fields, filled across elicitation turns ----
    # A short, non-sensitive paraphrase used in traces/UI instead of the raw goal.
    goal_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One of BriefLevel {beginner, intermediate, advanced}; maps 1:1 to Difficulty.
    level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prior_knowledge: Mapped[str | None] = mapped_column(Text, nullable=True)
    time_budget_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sessions_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desired_outcomes: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    format_prefs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    suggested_subject: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        # Owner-scoped, time-ordered listing + the per-window session-quota
        # COUNT (R-M10) ride this composite index.
        Index("ix_learning_briefs_owner_created", "owner_id", "created_at"),
    )

    def __repr__(self) -> str:
        # Deliberately omits ``source_goal_enc`` (the ciphertext) AND the
        # plaintext (which isn't held here anyway) — a brief is identified by
        # id/owner/finalized-state only. Mirrors the BYOK redacting __repr__.
        state = "finalized" if self.finalized_at is not None else "in_progress"
        return f"<LearningBrief id={self.id!r} owner_id={self.owner_id!r} state={state}>"
