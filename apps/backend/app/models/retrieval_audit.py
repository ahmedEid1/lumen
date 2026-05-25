"""RetrievalAudit — one row per RAG retrieval, with chunks + scores.

Lumen v2 Phase H7. The dashboard view of "what did the retriever
actually find?" — without this, debugging a wrong tutor answer
means reproducing the user's exact query manually. With this, an
admin opens ``/admin/observability`` → "Retrieval Quality" and sees
the last N queries, their top-K chunks, and the similarity scores.

Schema fields:

* ``audit_id`` — 21-char nanoid, primary key.
* ``user_id`` — ``"__system__"`` sentinel allowed (eval suite,
  ingest pipelines). NOT NULL so the index is dense.
* ``feature`` — caller slug (``"tutor"``, ``"learning_path"``, ...).
  Same conventions as ``llm_calls.feature``.
* ``query`` — the raw search query the retriever was asked about.
  Stored as ``Text`` because user prompts can run long.
* ``course_id`` — nullable; the retriever scopes by course when
  it's called from the tutor, but a future "search across catalog"
  surface won't have a course id.
* ``chunks`` — JSONB list of ``{chunk_id, lesson_id, score, snippet}``
  records, up to 10. ``snippet`` is the first 120 chars of the
  chunk text — enough for an admin to recognise the content
  without storing the full body again.
* ``top_score`` — the best similarity score in the batch. Surfaced
  as a column (not just inside ``chunks``) so the dashboard can
  sort + filter on "low-quality retrievals" cheaply.
* ``created_at`` — tz-aware, server default ``now()``.

The score convention is **lower is more similar** (pgvector's
cosine distance ``<=>``). The retrieval helper already orders
ascending by ``cosine_distance``, so the audit row's ``chunks`` are
recorded in retrieval order and ``top_score`` is ``chunks[0].score``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin

# Max snippet length captured per chunk. 120 chars is enough for an
# admin to recognise the source paragraph without re-storing the
# full chunk text (already in ``lesson_chunks.text``).
SNIPPET_MAX_CHARS = 120

# Max chunks captured per retrieval. The retriever's default
# ``top_k`` is 5; the audit cap is 10 so callers that bump
# ``top_k`` for a debug session still fit cleanly.
MAX_CHUNKS_PER_AUDIT = 10


class RetrievalAudit(IdMixin, Base):
    """One row per RAG retrieval — see module docstring."""

    __tablename__ = "retrieval_audits"
    __table_args__ = (
        Index(
            "ix_retrieval_audits_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_retrieval_audits_feature_created",
            "feature",
            "created_at",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    course_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chunks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # ``top_score`` is a plain float — lower is better under cosine
    # distance. Nullable because a query that returns zero hits has
    # no top score; the dashboard renders that case as "no results".
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "MAX_CHUNKS_PER_AUDIT",
    "SNIPPET_MAX_CHARS",
    "RetrievalAudit",
]
