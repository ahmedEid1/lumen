"""drop lesson_progress.payload

Rebuild Cut A3: ``LessonProgress.payload`` was a JSONB mirror of the
latest quiz submission (answers + score + passed). Since iteration 47
introduced the append-only ``quiz_attempts`` table (revision 0004),
``QuizAttempt`` is the single source of truth for attempt history:
verbatim answers, score, pass/fail, and a server-side timestamp all
land there on every submission. ``LessonProgress.score`` still holds
the latest score for the certificate-percentage calculation, so the
payload column had no remaining read site outside its own write.

Reversible: downgrade re-adds the column with the original
``NOT NULL DEFAULT '{}'::jsonb`` so an older app image can roll back
without seeing a missing-column error. Historical attempt data
cannot be reconstructed into the mirror, but ``quiz_attempts`` keeps
the full record either way.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("lesson_progress", "payload")


def downgrade() -> None:
    op.add_column(
        "lesson_progress",
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
