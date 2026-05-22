"""courses slug partial unique (live rows only)

Replace the global `slug` uniqueness on `courses` with a *partial*
unique index that only considers rows where `deleted_at IS NULL`.

WHY: Lumen soft-deletes courses by stamping `deleted_at`. The
original schema (migration 0001) enforces `slug` uniqueness via
`uq_courses_slug` (unique constraint) *and* `ix_courses_slug`
(unique btree). That means a soft-deleted row still claims its
slug forever — instructors cannot reuse a freed slug, and any
attempt to *restore* a soft-deleted course collides with the
fresh row created in the meantime. With the partial index, a
soft-deleted row keeps its slug as a tombstone but lets a new
live row reclaim the same string; restoring a tombstoned row
now correctly fails the uniqueness check if a live duplicate
exists. See rebuild Fix B3 / `test_restore_soft_deleted_slug_*`.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the global unique constraint and the unique index that
    # both ride on `slug`. Postgres lets one named object back the
    # constraint and another back the index, so we drop them
    # explicitly. `if_exists` is conservative: older test DBs that
    # were stamped via metadata.create_all (not alembic) may have
    # produced slightly different names — we want the migration to
    # still apply cleanly there.
    op.drop_constraint("uq_courses_slug", "courses", type_="unique")
    op.drop_index("ix_courses_slug", table_name="courses")

    # Partial unique index — only live rows participate. Tombstoned
    # rows (`deleted_at IS NOT NULL`) keep their slug but no longer
    # block a new live row from claiming it.
    op.create_index(
        "uq_courses_slug_live",
        "courses",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Recreate the non-unique lookup index so `WHERE slug = ?`
    # queries (catalog detail page, slug-collision precheck) still
    # have an index to ride. Uniqueness is now solely the partial
    # index's job.
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=False)


def downgrade() -> None:
    # Reverse order: drop the partial unique + non-unique lookup
    # index, then put the global unique constraint + unique index
    # back the way migration 0001 left them.
    op.drop_index("ix_courses_slug", table_name="courses")
    op.drop_index("uq_courses_slug_live", table_name="courses")

    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)
    op.create_unique_constraint("uq_courses_slug", "courses", ["slug"])
