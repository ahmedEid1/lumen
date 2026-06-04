"""idempotency_keys

S4.2 / ADR-0028 §"New model: IdempotencyKey". Phase A (additive, zero-downtime).
Creates the ``idempotency_keys`` table — clone is the first endpoint to honor
``Idempotency-Key`` (ADR-0028 §Consequences), seeding this infrastructure for
the rest of v1.

What it does: ``CREATE TABLE idempotency_keys`` (IdMixin + TimestampMixin shape)
with the ``uq_idem_user_key`` unique constraint on ``(user_id, idempotency_key)``
and a CASCADE FK to ``users`` (a deleted user's keys go with them). New table,
invisible to old pods.

Down: drop the table.

Phase: A (additive). Net-new table — safe on any deploy; lands BEFORE the gated
0043 NOT-NULL boundary (HOUSE RULES / test_migration_chain).

Chain position: 0046 -> 0047 -> 0048 -> 0049 -> 0043 (head). 0043's
down_revision is re-pointed to 0049 so the gated boundary stays LAST.

Revision ID: 0049
Revises: 0048
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0049"
down_revision: str | Sequence[str] | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.String(length=80), nullable=False),
        sa.Column("response_target_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_idempotency_keys_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_idem_user_key"),
    )
    # TimestampMixin indexes ``created_at`` (a cheap sweep-by-age helper for the
    # expired-key cleanup).
    op.create_index(
        op.f("ix_idempotency_keys_created_at"),
        "idempotency_keys",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_idempotency_keys_created_at"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
