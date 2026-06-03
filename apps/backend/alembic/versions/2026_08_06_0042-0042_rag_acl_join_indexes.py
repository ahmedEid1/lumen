"""rag_acl_join_indexes

S2/RAG.42 / ADR-0029 §D5.1 + DR-15. Phase A (concurrent, additive). Adds the
index that keeps the RAG ACL JOIN's live-lesson filter index-backed so the
extra ``Course`` JOIN + ``retrieval_acl_clause`` predicate hold the R-U7 perf
budget after S2.8a's find_relevant_chunks change.

The courses-side ACL composite is already ``ix_courses_listed`` (created in
0033 — the design-spec consolidated ADR-0029's ``ix_courses_acl`` into it by
appending ``owner_id``), so this migration only adds the lessons-side partial
index:

  ``CREATE INDEX CONCURRENTLY ix_lessons_module_id_live ON lessons (module_id)
    WHERE deleted_at IS NULL;``

Built in an autocommit block (CONCURRENTLY can't run in a transaction); DROP IF
EXISTS first so a failed prior build (INVALID index) is re-runnable.

Down: ``DROP INDEX CONCURRENTLY IF EXISTS``.

Phase: A (concurrent, no table lock — safe on the live fleet mid-traffic).

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
# INTEGRATION: re-point at merge. Chain is 0033 -> 0041 -> 0042 -> 0043 -> 0044.
down_revision: str | Sequence[str] | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"

_INDEX = "ix_lessons_module_id_live"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON lessons (module_id) WHERE deleted_at IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
