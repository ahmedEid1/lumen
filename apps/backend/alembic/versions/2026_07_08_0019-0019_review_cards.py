"""review_cards (FSRS-6 spaced-repetition state)

Rebuild Phase E4: per-learner spaced-repetition queue backed by the
Free Spaced Repetition Scheduler v6 (`fsrs` Python package). Each
row is one card for a (user, lesson) pair — quiz lessons only for
v1; we may broaden to all lesson types in a future cut once we have
data on what learners actually find useful to re-review.

Key shape decisions:

* ``stability`` + ``difficulty`` (floats) — the two FSRS memory-state
  variables. ``stability`` is days until retrievability decays to
  ``desired_retention`` (~0.9); ``difficulty`` is 1.0-10.0 and reflects
  how hard the learner finds the material. Both are produced by the
  scheduler on every review.
* ``state`` — enum mirroring FSRS' ``Learning / Review / Relearning``
  plus a pre-FSRS ``new`` state for cards that have never been graded.
* ``step`` — learning-step counter used by FSRS while in Learning
  or Relearning (NULL once graduated to Review).
* ``due_at`` + index on (user_id, due_at) — the queue read is
  ``WHERE user_id = :u AND due_at <= now() ORDER BY due_at``; the
  composite index makes that an index-only scan.
* ``UniqueConstraint(user_id, lesson_id)`` — :func:`ensure_card` is
  called on every quiz submission and must be idempotent.

Coordination note: this migration is numbered 0019 because Phase E0
landed first with 0017 + 0018 (pgvector + lesson_chunks). If the
orchestrator reshuffles phase ordering, the number may need bumping
(or the alembic chain rewriting) — that's the merge-time concern of
whoever lands last.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-08
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_cards",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            sa.String(length=64),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stability", sa.Float(), nullable=False, server_default="0"),
        sa.Column("difficulty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("step", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_reviews", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("user_id", "lesson_id", name="uq_review_cards_user_lesson"),
    )
    op.create_index(
        "ix_review_cards_user_due",
        "review_cards",
        ["user_id", "due_at"],
    )
    op.create_index(
        "ix_review_cards_lesson_id",
        "review_cards",
        ["lesson_id"],
    )
    op.create_index(
        "ix_review_cards_created_at",
        "review_cards",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_cards_created_at", table_name="review_cards")
    op.drop_index("ix_review_cards_lesson_id", table_name="review_cards")
    op.drop_index("ix_review_cards_user_due", table_name="review_cards")
    op.drop_table("review_cards")
