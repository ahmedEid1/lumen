"""course_draft_traces — self-critique authoring reasoning trace

Lumen v2 Phase I3. One row per step in a critique-revise loop run
(researcher → outliner → critic → reviser → lesson_drafter →
final_critic). Sibling table to ``agent_traces`` (H7); kept separate
because the read pattern is instructor-scoped (no admin gating) and
the schema is authoring-specific (FKs to ``courses`` and an opaque
``draft_id`` correlation token).

See ``app/models/course_draft_trace.py`` for the full design notes —
this migration is the schema-only counterpart.

Three indexes, matched to the three read paths:

* ``(draft_id, step_index)`` — the studio timeline view.
* ``(course_id, created_at)`` — course-scoped lookup.
* ``(user_id, created_at)`` — per-instructor recent activity.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "course_draft_traces",
        sa.Column("id", sa.String(length=64), primary_key=True),
        # Opaque per-run correlation token. NOT a FK — the
        # orchestrator mints it; there is no parent "drafts" table.
        sa.Column("draft_id", sa.String(length=64), nullable=False),
        # Nullable: pre-outline-acceptance steps run before any
        # course row exists. SET NULL on course delete so an admin
        # purging a course doesn't lose the forensic trail.
        sa.Column(
            "course_id",
            sa.String(length=64),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column(
            "step_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # FK to the cost meter so we can drill from a metered LLM
        # call into the trace step that spawned it. SET NULL on
        # delete — same forensic-preservation logic as agent_traces.
        sa.Column(
            "parent_call_id",
            sa.String(length=64),
            sa.ForeignKey("llm_calls.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Self-referential FK for the trace tree. CASCADE so pruning
        # a root trace removes its subtree atomically.
        sa.Column(
            "parent_trace_id",
            sa.String(length=64),
            sa.ForeignKey("course_draft_traces.id", ondelete="CASCADE"),
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
    op.create_index(
        "ix_course_draft_traces_draft_id_step_index",
        "course_draft_traces",
        ["draft_id", "step_index"],
    )
    op.create_index(
        "ix_course_draft_traces_course_created",
        "course_draft_traces",
        ["course_id", "created_at"],
    )
    op.create_index(
        "ix_course_draft_traces_user_created",
        "course_draft_traces",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_draft_traces_user_created",
        table_name="course_draft_traces",
    )
    op.drop_index(
        "ix_course_draft_traces_course_created",
        table_name="course_draft_traces",
    )
    op.drop_index(
        "ix_course_draft_traces_draft_id_step_index",
        table_name="course_draft_traces",
    )
    op.drop_table("course_draft_traces")
