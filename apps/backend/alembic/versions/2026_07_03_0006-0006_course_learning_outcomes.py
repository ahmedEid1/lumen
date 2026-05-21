"""course learning_outcomes

Adds a JSONB ``learning_outcomes`` column to ``courses`` for the
"what you'll learn" bullet list shown above the syllabus.

Server-default ``[]`` so existing rows backfill safely and the
column can be NOT NULL.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-03
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "learning_outcomes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("courses", "learning_outcomes")
