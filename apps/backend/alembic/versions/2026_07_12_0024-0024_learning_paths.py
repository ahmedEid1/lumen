"""learning_paths + learning_path_steps — personalized goal-to-curriculum agent

Lumen v2 Phase I5. Two new tables backing the learning-path agent:

* ``learning_paths`` — one row per learner per goal. ``status`` is
  ``"active" | "archived"``; only one ``"active"`` per user, enforced
  via a partial unique index (mirrors the pattern used for
  ``courses.slug`` in 0010). ``next_action`` is a JSONB blob holding
  the agent's "what to do today" suggestion (course + kind).
  ``rationale`` is the free-form natural-language reasoning the LLM
  produced; we keep it verbatim so the "show me how the agent thinks"
  trace can render it.

* ``learning_path_steps`` — N rows per path, each one a chosen
  course inside a named milestone. ``course_slug`` is denormalised
  alongside ``course_id`` so the rendered path stays stable if a
  course slug rotates between re-plans (the FK guarantees the
  course still exists, the slug column makes the UI render without
  joining back to ``courses`` on every read).

Both tables use the ``user_id`` / ``course_id`` FK convention from
the rest of the schema (cascade on delete — a learner's removal
takes their paths with them; a course removal would null out the
plan-step rows it appeared in, but we use CASCADE here to keep the
domain object consistent — a path with vanished steps would be
worse than a removed path).

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-12
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- learning_paths ----------
    op.create_table(
        "learning_paths",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        # ``next_action`` is the "what to do today" hint the agent
        # returned. Shape: ``{course_slug: str, kind: str}`` or null
        # when the agent had no suggestion. JSONB keeps it queryable
        # without a schema bump.
        sa.Column(
            "next_action",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Stamped the moment the monthly beat job re-runs the planner.
        # Used by the beat job's staleness filter (``< now - 30d``).
        sa.Column(
            "replanned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Index for the per-user lookup ("does this user have a path?").
    op.create_index(
        "ix_learning_paths_user_id",
        "learning_paths",
        ["user_id"],
    )
    # Partial unique on ``(user_id)`` filtered to ``status='active'``
    # — only one active path per user. Archived paths can pile up
    # (they're the history of past plans).
    op.create_index(
        "uq_learning_paths_user_active",
        "learning_paths",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # ---------- learning_path_steps ----------
    op.create_table(
        "learning_path_steps",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "path_id",
            sa.String(length=64),
            sa.ForeignKey("learning_paths.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("milestone_name", sa.String(length=120), nullable=False),
        # Week-range string literally as the LLM returned it
        # (``"1-4"`` / ``"5-12"``). We don't normalise to a numeric
        # pair because the agent occasionally returns open ranges
        # ("13+") and the UI just renders this verbatim.
        sa.Column("milestone_weeks", sa.String(length=24), nullable=False),
        sa.Column(
            "course_id",
            sa.String(length=64),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Denormalised so the UI doesn't join ``courses`` to render
        # the path. Stays consistent with ``course_id`` at write time
        # (the service resolves slugs against the catalog before
        # persisting). If a course's slug rotates after the path is
        # built, the path still resolves through the FK and the
        # rendered slug stays the one the learner saw.
        sa.Column("course_slug", sa.String(length=220), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # The primary read path is "all steps for this path, in order".
    op.create_index(
        "ix_learning_path_steps_path_position",
        "learning_path_steps",
        ["path_id", "position"],
    )
    op.create_index(
        "ix_learning_path_steps_course_id",
        "learning_path_steps",
        ["course_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_learning_path_steps_course_id",
        table_name="learning_path_steps",
    )
    op.drop_index(
        "ix_learning_path_steps_path_position",
        table_name="learning_path_steps",
    )
    op.drop_table("learning_path_steps")

    op.drop_index(
        "uq_learning_paths_user_active",
        table_name="learning_paths",
    )
    op.drop_index(
        "ix_learning_paths_user_id",
        table_name="learning_paths",
    )
    op.drop_table("learning_paths")
