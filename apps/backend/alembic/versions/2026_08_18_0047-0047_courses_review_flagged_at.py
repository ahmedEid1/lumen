"""courses_review_flagged_at

S6 gate F3 / R-S11. Phase A (additive, zero-downtime). Adds
``courses.review_flagged_at`` — the out-of-band "needs admin re-review" signal
for an APPROVED course that accumulated enough OPEN user reports.

Why a separate column instead of flipping ``moderation_state`` to
``pending_review``: ``is_publicly_listed`` requires ``moderation_state ==
approved``, so requeueing a vetted course to ``pending_review`` on a weak
3-report signal would AUTO-UNLIST it — the exact R-S11 violation the requeue's
own docstring denies. Stamping ``review_flagged_at`` instead leaves
``moderation_state`` untouched (course stays ``approved`` → stays listed) while
the admin moderation queue surfaces the course for re-confirmation via a
``review_flagged_at IS NOT NULL`` arm. Every admin transition clears it.

What it does:

1. ``ADD COLUMN courses.review_flagged_at TIMESTAMPTZ NULL`` — instant on PG17
   (nullable, no default, no rewrite).
2. ``CREATE INDEX ix_courses_review_flagged (review_flagged_at) WHERE
   review_flagged_at IS NOT NULL`` — partial, so only the handful of flagged
   courses are indexed; serves the queue's flagged arm.

Down: drop the index, then the column.

Phase: A (additive). Net-new nullable column + partial index — invisible to old
pods (they never read or write it), so it is safe on any deploy and lands
BEFORE the gated 0043 NOT-NULL boundary (HOUSE RULES / test_migration_chain).

Chain position: new Phase-A revisions chain BETWEEN the current last Phase-A
revision (0046 course_reports) and the gated 0043 boundary, so the boundary
stays LAST. Chain: 0042 -> 0044 -> 0045 -> 0046 -> 0047 -> 0043 (head).

Revision ID: 0047
Revises: 0046
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047"
# HOUSE RULES: chain BETWEEN 0046 and the gated 0043 boundary. 0047 chains off
# 0046; 0043's down_revision is re-pointed to 0047 so the gated boundary stays
# LAST (chain: 0044 -> 0045 -> 0046 -> 0047 -> 0043).
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    # Additive nullable timestamp — instant on PG17 (no default, no rewrite).
    op.add_column(
        "courses",
        sa.Column("review_flagged_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index: only flagged courses are indexed (the queue's flagged arm).
    op.create_index(
        "ix_courses_review_flagged",
        "courses",
        ["review_flagged_at"],
        postgresql_where=sa.text("review_flagged_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_courses_review_flagged", table_name="courses")
    op.drop_column("courses", "review_flagged_at")
