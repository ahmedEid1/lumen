"""user_llm_credentials — encrypted per-user BYOK provider keys (S5.3).

ADR-0027 §"Data model changes". One row per (user, provider) live
credential. The API key is **never** stored in plaintext: the foundation
``app.core.secrets_crypto`` envelope-encrypts it into the opaque
``enc_blob`` (nonce‖ct‖tag of the key, with the wrapped DEK + KEK version
packed into the blob header). ``key_version`` mirrors the blob's active KEK
version so a rotation pass can target rows by version without unpacking
every blob; ``key_fingerprint`` (SHA-256 hex) powers idempotency/dedupe
(FR-BYOK-08) and the validate anti-oracle distinct-key cap (R-S4);
``last4`` is the only key-derived value safe to render.

There is **no** plaintext key column, ever, and **no** ``api_base`` /
``host`` / ``url`` column — the base URL comes exclusively from the
allowlisted registry (DR-17), which is what structurally closes SSRF.

Constraints (ADR-0027 §Data model):

* ``uq_user_llm_credential_provider`` — partial unique ``(user_id, provider)
  WHERE deleted_at IS NULL`` (one live credential per provider, FR-BYOK-08).
* ``uq_user_llm_credential_active`` — partial unique ``(user_id) WHERE
  is_active AND deleted_at IS NULL`` (≤1 active credential per user).
* ``ix_user_llm_credentials_user`` on ``(user_id)``.

Soft-delete via ``deleted_at`` so a removed key never orphans audit/turn
history (the streaming turn FK is ON DELETE SET NULL).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


# Validation-status literals (ADR-0027 §Data model). Kept in Python (not a
# PG enum) so the set can grow without a migration.
VALIDATION_UNVALIDATED = "unvalidated"
VALIDATION_VALID = "valid"
VALIDATION_INVALID = "invalid"
VALIDATION_ERROR = "error"
VALIDATION_NEEDS_ATTENTION = "needs_attention"


class UserLLMCredential(IdMixin, TimestampMixin, Base):
    """An envelope-encrypted BYOK credential. See module docstring."""

    __tablename__ = "user_llm_credentials"
    __table_args__ = (
        # Partial unique: only live (non-soft-deleted) rows participate, so a
        # user may re-add a provider after removing the old key (FR-BYOK-08).
        # A plain UniqueConstraint cannot be partial, so this is a partial
        # unique Index.
        Index(
            "uq_user_llm_credential_provider",
            "user_id",
            "provider",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_user_llm_credential_active",
            "user_id",
            unique=True,
            postgresql_where=text("is_active AND deleted_at IS NULL"),
        ),
        Index("ix_user_llm_credentials_user", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    # Envelope ciphertext (foundation secrets_crypto blob). Never the
    # plaintext key. ``key_version`` mirrors the active KEK version baked
    # into the blob header so a rotation can target rows by version.
    enc_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    last4: Mapped[str] = mapped_column(String(8), nullable=False)

    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    allow_platform_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VALIDATION_UNVALIDATED, server_default="unvalidated"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


__all__ = [
    "VALIDATION_ERROR",
    "VALIDATION_INVALID",
    "VALIDATION_NEEDS_ATTENTION",
    "VALIDATION_UNVALIDATED",
    "VALIDATION_VALID",
    "UserLLMCredential",
]
