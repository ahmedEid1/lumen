"""drop discussion_subscriptions

Rebuild Cut A4: ``DiscussionSubscription`` shipped without a delivery
mechanism. There was no Celery digest, no email trigger, and the
"is this user subscribed?" boolean was only used by the UI to toggle
a bell button. Reply notifications are now sent directly to the
thread author (the only consumer the fanout ever materially served),
so the whole subscription table is removable.

Reversible: downgrade re-creates the table with the original schema
so an older app image can roll back. Historical subscription rows
cannot be reconstructed, but no callers ever read the data.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_discussion_subscriptions_discussion_id",
        table_name="discussion_subscriptions",
    )
    op.drop_table("discussion_subscriptions")


def downgrade() -> None:
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
