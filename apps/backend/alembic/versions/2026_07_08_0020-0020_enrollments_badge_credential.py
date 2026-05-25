"""enrollments.badge_credential JSONB

Rebuild Phase E5: store the signed Open Badges 3.0 / W3C VC credential
alongside the existing ``certificate_id``. Populated by
``app.services.enrollment._maybe_issue_certificate`` on 100% lesson
completion. Nullable because (a) historical enrollments that already
have a ``certificate_id`` predate OB3 issuance and we don't backfill
them automatically, and (b) the column is logically derived from
``user`` + ``course`` + ``certificate_id`` — at any time the platform
can re-issue by calling the service again, so missing rows are
recoverable rather than data-lossy.

Numbered ``0020`` per the original spec: E0's pgvector + lesson_chunks
migrations took ``0017`` and ``0018``, E4's review_cards took ``0019``,
and Phase E5 follows at ``0020``.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-08
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "enrollments",
        sa.Column(
            "badge_credential",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("enrollments", "badge_credential")
