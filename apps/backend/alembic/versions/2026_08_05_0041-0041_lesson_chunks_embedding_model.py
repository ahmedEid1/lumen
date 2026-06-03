"""lesson_chunks_embedding_model

S2/RAG.41 / ADR-0029 §D6 + DR-14. Phase A (additive, backfilled). Adds the
per-chunk embedding provenance columns ``embedding_model`` + ``embedding_dim``
so a platform embedding-model change does NOT mass-invalidate (R-C3): existing
chunks stay queryable under their recorded model, and FR-EMBED-04 drift
detection can compare a chunk's recorded model to the current provider.

What it does:

1. ``ADD COLUMN embedding_model VARCHAR(128) NULL`` + ``embedding_dim SMALLINT
   NULL`` — nullable first, no table rewrite (instant on PG17).
2. **Operator-confirmed batched backfill (DR-14, never assumed):** backfill
   existing chunks with the model that ACTUALLY produced them. The model value
   is read from the ``EMBEDDING_BACKFILL_MODEL`` env (operator passes the
   deployed ``EMBEDDING_PROVIDER`` model at backfill time); the dim from
   ``EMBEDDING_BACKFILL_DIM`` (default the module constant 384). If
   ``EMBEDDING_BACKFILL_MODEL`` is UNSET the backfill is SKIPPED and the column
   STAYS nullable (do not force a wrong attribution) — migration 0043's NOT-NULL
   then refuses until a real backfill ran. Chunked by PK range, brief
   autocommit per batch, to avoid a long lock on the live table.

Down: drop both columns (additive, fully reversible).

Phase: A (additive). Apply with the ingest image that stamps the columns;
operator passes EMBEDDING_BACKFILL_MODEL.

Revision ID: 0041
Revises: 0033
Create Date: 2026-08-05
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
# INTEGRATION: re-point at merge. Chain is 0033 -> 0041 -> 0042 -> 0043 -> 0044.
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHASE = "A"

_DEFAULT_DIM = 384
_BATCH = 5000


def upgrade() -> None:
    op.add_column(
        "lesson_chunks", sa.Column("embedding_model", sa.String(length=128), nullable=True)
    )
    op.add_column("lesson_chunks", sa.Column("embedding_dim", sa.SmallInteger(), nullable=True))

    # Operator-confirmed backfill (DR-14). Assumed-NEVER: if the operator hasn't
    # confirmed the deployed model, skip — the column stays nullable and 0043
    # will refuse to tighten until a real backfill runs.
    model = os.environ.get("EMBEDDING_BACKFILL_MODEL")
    if not model:
        return
    dim = int(os.environ.get("EMBEDDING_BACKFILL_DIM", _DEFAULT_DIM))

    bind = op.get_bind()
    while True:
        res = bind.execute(
            sa.text(
                """
                WITH batch AS (
                    SELECT id FROM lesson_chunks WHERE embedding_model IS NULL LIMIT :lim
                )
                UPDATE lesson_chunks c
                SET embedding_model = :model, embedding_dim = :dim
                FROM batch
                WHERE c.id = batch.id
                RETURNING c.id
                """
            ),
            {"lim": _BATCH, "model": model, "dim": dim},
        )
        if not res.fetchall():
            break


def downgrade() -> None:
    op.drop_column("lesson_chunks", "embedding_dim")
    op.drop_column("lesson_chunks", "embedding_model")
