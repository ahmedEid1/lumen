"""Add course_id + user_message to tutor_turn_jobs.

L32 wires real pgvector retrieval into the streaming orchestrator.
The orchestrator runs inside the Celery task, which can only see what
the POST handler persisted to the turn row — so the turn needs to
carry the course context + the actual user message.

Both columns are nullable on the existing empty table: the streaming
flag is still off in prod, so no live row would be invalidated by a
NOT NULL constraint, but keeping them nullable means a follow-up
that re-uses the table for non-course turns (e.g. demo route without
a slug) doesn't need a second migration.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | Sequence[str] | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tutor_turn_jobs",
        sa.Column("course_id", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "tutor_turn_jobs",
        sa.Column("user_message", sa.Text(), nullable=True),
    )
    # ON DELETE SET NULL — if a course is hard-deleted (rare, admin
    # path only) we don't want to cascade-delete historical turns.
    # The retrieval simply degrades to "no course context" on replay.
    op.create_foreign_key(
        "fk_tutor_turn_jobs_course_id",
        source_table="tutor_turn_jobs",
        referent_table="courses",
        local_cols=["course_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tutor_turn_jobs_course_id", "tutor_turn_jobs", type_="foreignkey")
    op.drop_column("tutor_turn_jobs", "user_message")
    op.drop_column("tutor_turn_jobs", "course_id")
