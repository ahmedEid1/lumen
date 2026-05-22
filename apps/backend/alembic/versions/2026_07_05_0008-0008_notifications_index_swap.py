"""notifications_index_swap

Replace the (user_id, read_at) index on notifications with
(user_id, created_at). The list_for_user query in
app/repositories/notifications.py orders by created_at DESC and
filters only by user_id — read_at is mostly NULL and no query
filters by it. Swap to align the index with the real access pattern.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_notifications_user_id_read", table_name="notifications")
    op.create_index(
        "ix_notifications_user_id_created",
        "notifications",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id_created", table_name="notifications")
    op.create_index(
        "ix_notifications_user_id_read",
        "notifications",
        ["user_id", "read_at"],
    )
