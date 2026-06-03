"""courses_quarantined

S2.10 / DR-18-R2 + PR-12. Phase A (additive, zero-downtime). Adds
``courses.quarantined`` — the single source of truth for the csam/illegal
full-quarantine path, enforced in BOTH the Python authorizer (can_view_course)
AND the SQL clauses (publicly_listed_sql / retrieval_acl_clause owner-branch),
so a quarantined owner's frozen-not-deleted course cannot leak via catalog OR
RAG retrieval. ``severe_abuse`` is NOT this column — it stays a
``moderation_event.reason_code`` read (owner keeps view/edit; S6 scope).

What it does:

1. ``ADD COLUMN courses.quarantined BOOLEAN NOT NULL DEFAULT false`` — instant
   on PG17 (constant default, no rewrite).
2. Rebuild ``ix_courses_listed`` to add ``quarantined = false`` to the partial
   WHERE, using the PR-12 **CREATE-new-name-CONCURRENTLY-then-DROP-old** pattern
   (never DROP-then-CREATE — that would leave a no-index window on the catalog
   hot path). Build ``ix_courses_listed_v2`` CONCURRENTLY, then drop the old
   ``ix_courses_listed`` CONCURRENTLY, then (best-effort) rename v2 back to the
   canonical name so the model's ``__table_args__`` and a fresh create_all
   agree on the name.

Down: rebuild ``ix_courses_listed`` WITHOUT the quarantined predicate (same
CREATE-new-then-DROP-old discipline), then drop the column.

Phase: A (additive). Apply with the quarantine-aware authorizer release.

Revision ID: 0044
Revises: 0043
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
# INTEGRATION: re-point at merge. Chain is 0033 -> 0041 -> 0042 -> 0044 -> 0043.
# Phase A (quarantined column, instant constant default) is sequenced BEFORE the
# Phase D (0043 NOT-NULL) boundary so a `migrate.safe`-only deploy applies the
# column the visibility SQL references — were 0044 chained AFTER 0043, the safe
# upgrade would stop at the gated 0043 and run quarantine-aware code against a
# missing column (Codex P1 / Gate-C). Run test_migration_chain (S7.10).
down_revision: str | Sequence[str] | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"

_OLD = "ix_courses_listed"
_NEW = "ix_courses_listed_v2"
_COLS = "(visibility, moderation_state, status, subject_id, owner_id)"


def _rebuild_index(*, with_quarantine: bool) -> None:
    """CREATE-new-CONCURRENTLY then DROP-old-CONCURRENTLY (PR-12).

    Never leaves the catalog hot path without an index. DROP IF EXISTS first so
    a failed prior CONCURRENTLY build (INVALID index) is cleaned up.
    """
    where = "deleted_at IS NULL"
    if with_quarantine:
        where += " AND quarantined = false"
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_NEW}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NEW} ON courses {_COLS} WHERE {where}"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_OLD}")
        # Rename the new index back to the canonical name so the model's
        # __table_args__ and a fresh metadata create_all agree. ALTER INDEX
        # RENAME is a fast catalog-only operation (no rebuild).
        op.execute(f"ALTER INDEX {_NEW} RENAME TO {_OLD}")


def upgrade() -> None:
    # 1) Additive boolean with a constant default — instant on PG17.
    op.add_column(
        "courses",
        sa.Column("quarantined", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # 2) Rebuild the listing index WITH the quarantine predicate (PR-12).
    _rebuild_index(with_quarantine=True)


def downgrade() -> None:
    # Rebuild the index WITHOUT the quarantine predicate, then drop the column.
    _rebuild_index(with_quarantine=False)
    op.drop_column("courses", "quarantined")
