"""LessonChunk — per-lesson semantic chunk with embedding.

Rebuild Phase E0. One row per ~500-token slice of a lesson's text
content, with the slice's 384-dim embedding vector. Populated by the
``embeddings_ingest`` service on course publish and re-publish;
queried by ``embeddings_retrieval`` to support the course-scoped RAG
tutor (Phase E1) and the rest of the AI moat.

Why 384 dims: ``sentence-transformers/all-MiniLM-L6-v2`` (our default
local provider) emits 384, and ``text-embedding-3-small`` from
OpenAI accepts ``dimensions=384`` as a truncation knob — so the same
column shape works regardless of provider.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin

if TYPE_CHECKING:
    from app.models.course import Lesson


# Embedding dimensionality — kept as a module constant so the model,
# the migration, and every embedding provider can agree on one number.
EMBEDDING_DIM: int = 384


class LessonChunk(IdMixin, Base):
    """A single chunk of one lesson's text + its embedding vector."""

    __tablename__ = "lesson_chunks"
    __table_args__ = (
        UniqueConstraint("lesson_id", "chunk_index", name="uq_lesson_chunks_lesson_index"),
        Index("ix_lesson_chunks_lesson_id", "lesson_id"),
    )

    lesson_id: Mapped[str] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # The Vector type maps to pgvector's ``vector`` column. SQLAlchemy
    # treats the Python side as ``list[float]`` on read/write.
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Per-chunk embedding provenance (ADR-0029 §D6 / R-C3 / FR-EMBED-03).
    # Stamped by ``ingest_lesson`` from the resolving provider. Kept NULLABLE at
    # the ORM level: a platform model change does NOT mass-invalidate (existing
    # chunks stay queryable under their recorded model), and mixed-model within
    # a course mid-reindex is allowed transiently. Migrations 0041 (add
    # nullable) → 0042 (operator-confirmed backfill) → 0043 (NOT NULL, Phase-D-
    # gated) tighten the DB column once the fleet stamps them on every insert.
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # We don't pull in ``TimestampMixin`` because chunks are append-only
    # at the row level (re-ingest deletes + reinserts), so an
    # ``updated_at`` column would always equal ``created_at`` — noise.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lesson: Mapped[Lesson] = relationship()


__all__ = ["EMBEDDING_DIM", "LessonChunk"]
