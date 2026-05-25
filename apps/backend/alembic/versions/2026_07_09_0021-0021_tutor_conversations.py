"""tutor_conversations + tutor_messages (course-scoped RAG tutor)

Rebuild Phase E1: persisted chat history for the course tutor. Two
append-only tables — one row per conversation, one row per turn.
Schema notes:

* ``tutor_conversations`` is scoped to ``(user_id, course_id)``. We
  deliberately don't share conversations across courses — the
  tutor's citation invariant ("every claim ties back to a lesson
  in *this* course") would break the moment a learner asked a
  question whose context bled across courses.

* ``last_message_at`` is touched on every persisted assistant
  message. The composite index ``(user_id, course_id,
  last_message_at desc)`` serves the panel's "my recent
  conversations" view as an index-only range scan — no scan of
  ``tutor_messages`` for that surface.

* ``tutor_messages.citations`` is JSONB rather than a normalised
  side table because (a) it's read alongside the message in 100%
  of cases and (b) the citation count per message is bounded at
  ``top_k`` from retrieval (currently 5). A side table would
  burn 1 + N round trips for what trivially fits in one column.

* No soft-delete: a tutor transcript is a learner's private
  artefact, like email. When they hit "delete conversation" we
  hard-delete the row and cascade-drop the messages.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-09
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tutor_conversations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            sa.String(length=64),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Composite for the panel's "my recent conversations for this course"
    # read. The descending sort key is implemented via a regular
    # multi-column index — Postgres can scan it backwards for ORDER BY
    # ... DESC without an explicit DESC declaration on the index.
    op.create_index(
        "ix_tutor_conversations_user_course_last",
        "tutor_conversations",
        ["user_id", "course_id", "last_message_at"],
    )
    op.create_index(
        "ix_tutor_conversations_course_id",
        "tutor_conversations",
        ["course_id"],
    )

    op.create_table(
        "tutor_messages",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=64),
            sa.ForeignKey("tutor_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_tutor_messages_conv_created",
        "tutor_messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tutor_messages_conv_created", table_name="tutor_messages")
    op.drop_table("tutor_messages")
    op.drop_index(
        "ix_tutor_conversations_course_id", table_name="tutor_conversations"
    )
    op.drop_index(
        "ix_tutor_conversations_user_course_last",
        table_name="tutor_conversations",
    )
    op.drop_table("tutor_conversations")
