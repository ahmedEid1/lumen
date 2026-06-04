"""lesson_chunks_embedding_model_not_null

S2/RAG.43 / ADR-0029 §D6 (migration 0035 in the ADR's stale numbering) + DR-14.
**Phase D** (NOT-NULL tighten — release-gated, NOT a blind ``upgrade head``).

Precondition (operational gate, mirrors R-S8′ step 3): the new ingest image
that ALWAYS stamps ``embedding_model``/``embedding_dim`` is deployed to every
worker/API AND 0041's operator-confirmed backfill has drained (no NULL rows
remain). Only then does the column tighten to NOT NULL.

Safety: ``upgrade()`` first asserts there are ZERO ``embedding_model IS NULL``
rows. If any remain (backfill skipped because the operator didn't confirm a
model, or the fleet isn't fully on the stamping image), it RAISES rather than
forcing a wrong/empty value — Phase D is gated, not assumed (DR-14).

What it does (after the guard): ``ALTER COLUMN embedding_model SET NOT NULL``
+ ``embedding_dim SET NOT NULL`` (PG17 validates fast against a fully-populated
column; brief ACCESS EXCLUSIVE, no rewrite).

Down: drop the NOT NULL constraints (re-allow NULL).

Phase: D (release-gated). Apply via an explicit ``alembic upgrade 0043`` step in
the deploy runbook with ``ALLOW_PHASE_MIGRATION=1``, never a blind make migrate.

Chain position: this Phase-D NOT-NULL tighten is the LAST revision in the chain
(0042 -> 0044 -> 0045 -> 0046 -> 0047 -> 0043, head) so it sits AFTER every
Phase-A revision in the release window (incl. the ``courses.quarantined`` column
0044 the visibility SQL depends on, and the F3 ``courses.review_flagged_at``
column 0047). A ``migrate.safe``-only deploy therefore lands every additive
revision and stops cleanly at this gated boundary instead of running schema-
aware code against a missing column (Codex P1 / Gate-C).

Revision ID: 0043
Revises: 0047
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
# INTEGRATION: re-point at merge. Chain is 0042 -> 0044 -> 0045 -> 0046 -> 0047
# -> 0043. This Phase-D boundary stays LAST so it follows every Phase-A revision
# in the release window (the quarantine column 0044, the share-500 fix 0045, the
# S6.3 course_reports table 0046, and the F3 review_flagged_at column 0047); see
# the module docstring (Codex P1 / Gate-C + HOUSE RULES: new Phase-A revs insert
# BEFORE the boundary, never move it).
# Compatibility note (Codex confirm-round adjudication, 2026-06-04): re-parenting
# an applied revision would normally strand DBs stamped at old-0043-without-0045
# (0043 == new head -> no pending -> 0045 never applies). RULED INAPPLICABLE
# here: this chain is branch-only and pre-release — prod runs main (pre-0030,
# applies the whole chain fresh in this order at W12), CI uses transient DBs,
# and the single dev DB that ever held the old order has 0045's DDL applied and
# was re-stamped the same day. If an unknown DB ever IS in that state the
# failure is loud (POST /share NotNullViolation + the 0045 information_schema
# test), not silent. Do NOT re-parent applied revisions after W12 ships this
# chain to prod — from that point the boundary-last invariant must be satisfied
# by inserting new revisions, never by moving applied ones.
down_revision: str | Sequence[str] | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase D — NOT a blind upgrade head. The make-migrate guard / runbook applies
# this explicitly (PR-11).
PHASE = "D"


def upgrade() -> None:
    bind = op.get_bind()
    null_rows = bind.execute(
        sa.text("SELECT count(*) FROM lesson_chunks WHERE embedding_model IS NULL")
    ).scalar_one()
    if null_rows:
        raise RuntimeError(
            f"Refusing to set lesson_chunks.embedding_model NOT NULL: {null_rows} row(s) "
            "still NULL. Run 0041's operator-confirmed backfill (EMBEDDING_BACKFILL_MODEL) "
            "and confirm the fleet is on the stamping ingest image first (Phase D gate / DR-14)."
        )
    op.alter_column("lesson_chunks", "embedding_model", nullable=False)
    op.alter_column("lesson_chunks", "embedding_dim", nullable=False)


def downgrade() -> None:
    op.alter_column("lesson_chunks", "embedding_dim", nullable=True)
    op.alter_column("lesson_chunks", "embedding_model", nullable=True)
