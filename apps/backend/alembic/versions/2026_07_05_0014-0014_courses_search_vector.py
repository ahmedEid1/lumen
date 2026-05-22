"""courses.search_vector tsvector + GIN

Rebuild Cut A9: rip Meilisearch, swap to Postgres-native FTS. The
existing ``search_courses`` repo function already issued
``to_tsvector('english', title || ' ' || overview) @@
websearch_to_tsquery(...)`` inline, but recomputed the tsvector on
every search. This migration adds a GENERATED ALWAYS AS STORED
``search_vector`` column on ``courses`` + a GIN index on it, so the
same query plan picks up the index instead of recomputing per row.

The generated expression matches what the repository was hashing
inline so the search behaviour is identical for existing queries;
publishing/editing courses now updates the column automatically via
Postgres' generated-column machinery (no Celery worker needed).

Reversible: downgrade drops the GIN index and the column. Search
falls back to the inline ``to_tsvector`` path that the repo retained
for ILIKE-only matches.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-05
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE courses
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'english',
                coalesce(title, '') || ' ' || coalesce(overview, '')
            )
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_courses_search_vector ON courses USING GIN (search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_courses_search_vector")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS search_vector")
