"""byok_credentials — user_llm_credentials envelope-encrypted key store.

S5.3 / ADR-0027 §"Data model changes". Phase A (additive, zero-downtime,
reversible). Creates ``user_llm_credentials`` with the envelope ciphertext
columns (``enc_blob`` + ``key_version``), the masked-display metadata
(``key_fingerprint`` / ``last4``), the enable/active/fallback flags, the
validation-status fields, and a ``deleted_at`` soft-delete marker. There is
**no** plaintext-key column and **no** ``api_base``/``host``/``url`` column
(the base URL comes only from the allowlisted registry — DR-17).

Constraints/indexes:

* ``uq_user_llm_credential_provider`` — partial unique ``(user_id, provider)
  WHERE deleted_at IS NULL`` (one live credential per provider, FR-BYOK-08).
* ``uq_user_llm_credential_active`` — partial unique ``(user_id) WHERE
  is_active AND deleted_at IS NULL`` (≤1 active credential per user).
* ``ix_user_llm_credentials_user`` on ``(user_id)``.

The FK ``user_id -> users.id`` is ON DELETE CASCADE (deleting the user
takes their credentials with them).

Phase: A (additive). Apply with any deploy; the BYOK code is flag-gated OFF
(``feature_byok_enabled=false``) until the KEK is confirmed fleet-wide.

down_revision: "0032" — re-pointed at S5 merge (chains after the S1 role collapse).
chain internally 0038 -> 0039 -> 0040; at integration the head of the
landed chain (after S1/S2's revisions) replaces "0030" here.

Revision ID: 0038
Revises: 0032
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038"
# foundation head); the integrator re-points this at the real chain head.
down_revision: str | Sequence[str] | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DR-12 rollout phase annotation (S7.7 guard reads this).
PHASE = "A"

_TABLE = "user_llm_credentials"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=21), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=21),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        # Envelope ciphertext (secrets_crypto blob). Never the plaintext key.
        sa.Column("enc_blob", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("last4", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "allow_platform_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_validation_status",
            sa.String(length=20),
            nullable=False,
            server_default="unvalidated",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Partial uniques: one LIVE credential per provider, ≤1 active per user.
    op.create_index(
        "uq_user_llm_credential_provider",
        _TABLE,
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_user_llm_credential_active",
        _TABLE,
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND deleted_at IS NULL"),
    )
    op.create_index("ix_user_llm_credentials_user", _TABLE, ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_llm_credentials_user", table_name=_TABLE)
    op.drop_index("uq_user_llm_credential_active", table_name=_TABLE)
    op.drop_index("uq_user_llm_credential_provider", table_name=_TABLE)
    op.drop_table(_TABLE)
