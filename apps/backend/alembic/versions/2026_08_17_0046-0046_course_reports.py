"""course_reports

S6.3 / DR-20. Phase A (additive, zero-downtime). Net-new ``course_reports``
table — invisible to old pods (they never read or write it), so it is safe on
any deploy and lands BEFORE the gated 0043 NOT-NULL boundary (HOUSE RULES /
test_migration_chain).

What it does:

* ``CREATE TABLE course_reports`` — a user-filed report against a publicly-
  listed course (FR-MOD-11). ``course_id``/``reporter_id`` FK→ CASCADE (a
  course or reporter hard-delete removes its reports); ``resolved_by`` FK→
  SET NULL (a resolved-by admin who later deletes their account doesn't erase
  the report).
* Partial-unique ``uq_course_reports_open (course_id, reporter_id) WHERE
  status='open'`` — open-report coalescing: one reporter holds at most one OPEN
  report per course (a second report updates the existing row).
* ``ix_course_reports_status_created (status, created_at)`` — the admin
  cursor-paginated report queue (S6.4) filters on status + orders by recency.

Down: drop the table.

Revision ID: 0046
Revises: 0045
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046"
# HOUSE RULES: new Phase-A revisions chain BETWEEN 0045 and the gated 0043
# boundary. 0046 chains off 0045; 0043's down_revision is re-pointed to 0046 so
# the gated boundary stays LAST (chain: 0042 -> 0044 -> 0045 -> 0046 -> 0043).
down_revision: str | Sequence[str] | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"


def upgrade() -> None:
    op.create_table(
        "course_reports",
        sa.Column("id", sa.String(length=21), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(length=21),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_id",
            sa.String(length=21),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by",
            sa.String(length=21),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    # Open-report coalescing: at most one OPEN report per (course, reporter).
    op.create_index(
        "uq_course_reports_open",
        "course_reports",
        ["course_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    # Admin report-queue: filter by status, order by recency.
    op.create_index(
        "ix_course_reports_status_created",
        "course_reports",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_course_reports_status_created", table_name="course_reports")
    op.drop_index("uq_course_reports_open", table_name="course_reports")
    op.drop_table("course_reports")
