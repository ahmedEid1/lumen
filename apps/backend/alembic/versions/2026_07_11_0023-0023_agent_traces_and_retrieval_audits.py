"""agent_traces + retrieval_audits — observability substrate

Lumen v2 Phase H7. Two new tables that I2 (multi-agent tutor) and
I3 (self-critique authoring) will write into, and that the
``/admin/observability`` surface reads:

* ``agent_traces`` — one row per step in an agentic workflow.
  Tree-shaped via ``parent_trace_id``; linked to the metered LLM
  call (``parent_call_id`` → ``llm_calls.id``) when the step made
  one. Indexes mirror ``llm_calls``: ``(user_id, created_at)`` and
  ``(feature, created_at)`` for the dashboard views, plus a
  ``(parent_call_id)`` index for the "drill from a metered call into
  its trace tree" path.

* ``retrieval_audits`` — one row per RAG retrieval, with the top-K
  chunks and their similarity scores captured as JSONB. The
  retriever writes one row when called with ``audit=True``; the
  default (``audit=False``) leaves the table untouched so existing
  call sites don't change behaviour.

Both tables follow the ``llm_calls`` pattern from migration 0022:
``user_id`` is a plain ``String(64)`` with a ``"__system__"``
sentinel for system-initiated work, not a FK to ``users``. JSONB
for the open-ended payload + chunks columns so the schema can flex
as I2/I3 add new step kinds without follow-up migrations.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-11
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- agent_traces ----------
    op.create_table(
        "agent_traces",
        sa.Column("id", sa.String(length=64), primary_key=True),
        # FK to ``llm_calls.id``. SET NULL on delete so an admin
        # purging cost-meter rows doesn't cascade away the agentic
        # forensic trail. Nullable because the orchestrator's
        # "plan" step typically runs before any LLM call.
        sa.Column(
            "parent_call_id",
            sa.String(length=64),
            sa.ForeignKey("llm_calls.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # ``"__system__"`` sentinel allowed — same convention as
        # ``llm_calls`` (see migration 0022).
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column(
            "step_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # Self-referential FK builds the trace tree. CASCADE on
        # delete so pruning a root trace removes its whole subtree
        # atomically — leaving orphaned children would leak data
        # we just promised to forget (GDPR / TTL paths).
        sa.Column(
            "parent_trace_id",
            sa.String(length=64),
            sa.ForeignKey("agent_traces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Per-user recent activity (dashboard left rail).
    op.create_index(
        "ix_agent_traces_user_created",
        "agent_traces",
        ["user_id", "created_at"],
    )
    # Per-feature recent activity (filter by "tutor.multi_agent" etc.).
    op.create_index(
        "ix_agent_traces_feature_created",
        "agent_traces",
        ["feature", "created_at"],
    )
    # Drill from a metered LLM call into its trace tree — the API's
    # primary fetch path.
    op.create_index(
        "ix_agent_traces_parent_call_id",
        "agent_traces",
        ["parent_call_id"],
    )

    # ---------- retrieval_audits ----------
    op.create_table(
        "retrieval_audits",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=True),
        sa.Column(
            "chunks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        # Plain float — lower = better under cosine distance.
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_retrieval_audits_user_created",
        "retrieval_audits",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_retrieval_audits_feature_created",
        "retrieval_audits",
        ["feature", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieval_audits_feature_created",
        table_name="retrieval_audits",
    )
    op.drop_index(
        "ix_retrieval_audits_user_created",
        table_name="retrieval_audits",
    )
    op.drop_table("retrieval_audits")

    op.drop_index(
        "ix_agent_traces_parent_call_id",
        table_name="agent_traces",
    )
    op.drop_index(
        "ix_agent_traces_feature_created",
        table_name="agent_traces",
    )
    op.drop_index(
        "ix_agent_traces_user_created",
        table_name="agent_traces",
    )
    op.drop_table("agent_traces")
