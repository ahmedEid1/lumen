"""drop chat_messages

Rebuild Cut A8: per-course WebSocket chat. Untested under load, lossy
on reconnect, and ultimately replaced by lesson-scoped async comments
+ a course-level AI tutor in Phase D/E. Per Lumen 2.0 rebuild spec
section 3.2 the table goes now; the replacement surfaces ship later.

Reversible: downgrade re-creates the original table + two indices so
an older app image can roll back. Historical messages cannot be
reconstructed.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(
        "ix_chat_messages_course_id_created_at", table_name="chat_messages"
    )
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")


def downgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("author_id", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            ["course_id"], ["courses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_chat_messages_course_id_created_at",
        "chat_messages",
        ["course_id", "created_at"],
    )
    op.create_index(
        "ix_chat_messages_created_at", "chat_messages", ["created_at"]
    )
