"""drop bookmarks

Rebuild Cut A7: the Bookmark model + bookmarks table tracked which
courses a learner had "saved for later", but the state was redundant
with enrollment (anything a serious learner cared about they enrolled
in; anything they bookmarked-and-never-enrolled rotted). The legacy
audit flagged it as a UX anti-pattern; per Lumen 2.0 rebuild spec
section 3.2 we drop the surface entirely.

Reversible: downgrade re-creates the table with the original schema
so an older app image can roll back. Historical bookmark rows cannot
be reconstructed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_bookmarks_user_id_created_at", table_name="bookmarks")
    op.drop_index("ix_bookmarks_created_at", table_name="bookmarks")
    op.drop_table("bookmarks")


def downgrade() -> None:
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
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
            ["course_id"], ["courses.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "course_id", name="uq_bookmarks_user_course"
        ),
    )
    op.create_index(
        "ix_bookmarks_user_id_created_at",
        "bookmarks",
        ["user_id", "created_at"],
    )
    op.create_index("ix_bookmarks_created_at", "bookmarks", ["created_at"])
