"""quiz attempts

Append-only table of quiz submissions so learners and instructors
can see attempt history rather than just the latest score that
``LessonProgress.payload`` happens to be holding.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("enrollment_id", sa.String(length=64), nullable=False),
        sa.Column("lesson_id", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"], ["lessons.id"], ondelete="CASCADE"
        ),
    )
    # Covers the common "latest attempts for (enrollment, lesson)" query.
    op.create_index(
        "ix_quiz_attempts_enrollment_lesson_created",
        "quiz_attempts",
        ["enrollment_id", "lesson_id", "created_at"],
    )
    # Cross-cohort lesson stats (avg score per lesson, etc.).
    op.create_index("ix_quiz_attempts_lesson_id", "quiz_attempts", ["lesson_id"])


def downgrade() -> None:
    op.drop_index("ix_quiz_attempts_lesson_id", table_name="quiz_attempts")
    op.drop_index(
        "ix_quiz_attempts_enrollment_lesson_created", table_name="quiz_attempts"
    )
    op.drop_table("quiz_attempts")
