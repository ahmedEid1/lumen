"""lesson_chunks

Rebuild Phase E0: per-lesson semantic chunk store for the RAG tutor
(Phase E1) and downstream AI surfaces (E2, E3, E7). Each row is a
~500-token slice of a lesson's text content paired with its 384-dim
embedding vector. 384 dims because the default
``sentence-transformers/all-MiniLM-L6-v2`` model emits 384 — small
enough to self-host on a CPU, big enough to outperform classic IR on
short course text. The OpenAI provider also writes 384 dims by
passing ``dimensions=384`` to ``text-embedding-3-small`` so we can
swap providers without a re-index.

Index choice: HNSW with ``vector_cosine_ops``. We use cosine distance
in retrieval (``<=>`` operator) because embedding magnitudes carry
no information for these models. HNSW is the right default for a
read-heavy, append-on-publish workload — IVFFlat would need a
``REINDEX`` after ingest to perform well, which is operationally
expensive given courses are published one at a time. ``m=16,
ef_construction=64`` are the pgvector defaults; we accept them
unless / until we have evidence to tune.

ON DELETE CASCADE on ``lesson_id`` means a hard-deleted lesson
(rare — soft-delete is the norm) cleans up its chunks automatically.
For soft-deletes we leave the chunks in place; the retrieval helper
joins against live lessons and filters them out anyway.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-07
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# pgvector ships a SQLAlchemy type adapter; we import lazily inside
# the upgrade so this module is import-safe even on hosts where the
# package hasn't been installed yet (e.g. ``alembic --help`` at build
# time before deps install).


revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from pgvector.sqlalchemy import Vector

    op.create_table(
        "lesson_chunks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "lesson_id",
            sa.String(length=64),
            sa.ForeignKey("lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("lesson_id", "chunk_index", name="uq_lesson_chunks_lesson_index"),
    )
    op.create_index(
        "ix_lesson_chunks_lesson_id",
        "lesson_chunks",
        ["lesson_id"],
    )
    # HNSW index for cosine-distance ANN search. pgvector's defaults
    # (m=16, ef_construction=64) are appropriate for catalogs <1M chunks.
    op.execute(
        "CREATE INDEX ix_lesson_chunks_embedding_hnsw "
        "ON lesson_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lesson_chunks_embedding_hnsw")
    op.drop_index("ix_lesson_chunks_lesson_id", table_name="lesson_chunks")
    op.drop_table("lesson_chunks")
