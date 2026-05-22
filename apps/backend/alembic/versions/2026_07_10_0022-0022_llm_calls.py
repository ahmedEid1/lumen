"""llm_calls — per-call cost / token / latency meter

Lumen v2 Phase H1. New ``llm_calls`` table that records one row per LLM
round-trip through ``app.services.llm``. Powers:

* per-user 24h budget guard (sum cost_usd, filtered by user_id);
* admin cost rollups by feature + by day;
* failure forensics (status="error" rows carry ``error_kind``).

Schema notes:

* ``user_id`` is NOT NULL and carries a ``"__system__"`` sentinel
  for calls without a human owner (eval suite, ingest pipelines).
  This keeps the ``(user_id, created_at)`` composite index dense and
  the budget query free of NULL gymnastics.
* ``cost_usd`` is ``Numeric(10, 6)`` — six fractional digits is
  sub-1¢ resolution, comfortably more than the smallest plausible
  single-call cost (Groq llama-3.3-70b @ a few hundred tokens lands
  around $1e-4).
* Two composite indexes: ``(user_id, created_at)`` for the budget
  guard and the per-user admin view; ``(feature, created_at)`` for
  the "cost by feature this week" rollup. ``created_at`` is sorted
  ascending in the index but Postgres can scan backwards so a
  ``ORDER BY created_at DESC`` against either index is one
  index-only range scan with no sort step.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(length=64), primary_key=True),
        # See module docstring — NOT NULL with a sentinel ("__system__")
        # for system-initiated calls. No FK to ``users`` for the same
        # reason: the sentinel isn't a real user id.
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "prompt_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "completion_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_kind", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Budget-guard hot path: sum cost_usd WHERE user_id=X AND
    # created_at > now() - 24h. Composite (user_id, created_at) gives
    # an index-only range scan keyed on user_id with the time window
    # as a sargable range predicate.
    op.create_index(
        "ix_llm_calls_user_created",
        "llm_calls",
        ["user_id", "created_at"],
    )
    # Admin rollup: "cost by feature for the last 14 days". Same idea,
    # different leading column.
    op.create_index(
        "ix_llm_calls_feature_created",
        "llm_calls",
        ["feature", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_calls_feature_created", table_name="llm_calls")
    op.drop_index("ix_llm_calls_user_created", table_name="llm_calls")
    op.drop_table("llm_calls")
