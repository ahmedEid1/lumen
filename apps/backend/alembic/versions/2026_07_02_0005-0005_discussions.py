"""discussions and discussion_replies

Two-table flat-thread discussion forum per course (iter 77).
Top-level Discussion has title + body + author + soft-delete;
DiscussionReply is a flat list under it with author + body +
soft-delete. We deliberately don't nest replies — Stack-Overflow
style "answer + comments" beats infinite nesting for readability.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-02
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discussions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("author_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_discussions_course_created",
        "discussions",
        ["course_id", "created_at"],
    )
    op.create_table(
        "discussion_replies",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("discussion_id", sa.String(length=64), nullable=False),
        sa.Column("author_id", sa.String(length=64), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["discussion_id"], ["discussions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_discussion_replies_discussion_created",
        "discussion_replies",
        ["discussion_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discussion_replies_discussion_created", table_name="discussion_replies"
    )
    op.drop_table("discussion_replies")
    op.drop_index("ix_discussions_course_created", table_name="discussions")
    op.drop_table("discussions")
