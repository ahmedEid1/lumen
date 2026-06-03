"""llm_calls_billing_mode — per-row billing attribution.

S5.4 / ADR-0027 §"Data model changes". Phase A (additive, zero-downtime,
reversible). Adds ``llm_calls.billing_mode VARCHAR(16) NOT NULL DEFAULT
'platform'`` — a Postgres 17 fast-default (no table rewrite). Old-fleet
INSERTs during a rolling deploy fill ``'platform'`` correctly (pre-deploy
traffic is all platform), so no backfill window is needed.

The new ``quota_exceeded`` status value (DR-11/16 sentinel rows) needs no
schema change — ``status`` is already ``VARCHAR(24)`` and the literal is a
Python constant.

Phase: A (additive). Apply with any deploy.

down_revision: "0038" (S5 internal chain).

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.add_column(
        "llm_calls",
        sa.Column(
            "billing_mode",
            sa.String(length=16),
            nullable=False,
            server_default="platform",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "billing_mode")
