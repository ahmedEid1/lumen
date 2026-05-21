"""discussion_subscriptions

Adds opt-in subscriptions per thread (iter 90). Authors auto-
subscribe at thread create; repliers auto-subscribe at reply.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discussion_subscriptions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("discussion_id", sa.String(length=64), nullable=False),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["discussion_id"], ["discussions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "discussion_id", name="uq_discussion_subscriptions_user_thread"
        ),
    )
    op.create_index(
        "ix_discussion_subscriptions_discussion_id",
        "discussion_subscriptions",
        ["discussion_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discussion_subscriptions_discussion_id",
        table_name="discussion_subscriptions",
    )
    op.drop_table("discussion_subscriptions")
