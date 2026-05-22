"""Top-k cosine-similarity retrieval over lesson chunks.

Rebuild Phase E0. Used by the RAG tutor (Phase E1) and any future
"explain this lesson" / "what else covers X" surface. The helper
intentionally returns ORM ``LessonChunk`` rows with their parent
``Lesson`` eagerly loaded — callers need the lesson id and title to
render citations, and a second SELECT per chunk would defeat the
point of the HNSW index doing one fast pass over the data.

The cosine-distance operator we use (``<=>``) only works when the
HNSW index is present, but Postgres will silently fall back to a
sequential scan + the same distance computation if the index isn't
there. That's the right failure mode in dev (and in tests, which
create the schema without the HNSW index — we don't want test setup
to depend on real ANN tuning).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.course import Lesson, Module
from app.models.lesson_chunk import LessonChunk
from app.services.embeddings import EmbeddingProvider, get_provider

log = get_logger(__name__)


async def find_relevant_chunks(
    db: AsyncSession,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    provider: EmbeddingProvider | None = None,
) -> list[LessonChunk]:
    """Return the ``top_k`` chunks most semantically similar to ``query``.

    Restricted to live lessons inside ``course_id`` — soft-deleted
    lessons (``Lesson.deleted_at IS NOT NULL``) are filtered out, and
    chunks belonging to lessons in other courses are unreachable. The
    caller is responsible for any further authz check (e.g. "is the
    asker enrolled or the owner?") — this helper is data-layer only.
    """
    if not query.strip() or top_k <= 0:
        return []

    prov = provider or get_provider()
    [query_vec] = prov.embed([query])

    # ``<=>`` is the cosine distance operator (1 - cosine similarity);
    # lower = more similar. We order ascending and limit. The join to
    # Lesson + Module restricts to the course and filters soft-deletes.
    # ``selectinload(LessonChunk.lesson)`` loads each chunk's parent
    # lesson in a single follow-up SELECT — callers render citations
    # off of ``chunk.lesson.title``.
    stmt = (
        select(LessonChunk)
        .join(Lesson, Lesson.id == LessonChunk.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .where(
            Module.course_id == course_id,
            Lesson.deleted_at.is_(None),
        )
        .order_by(LessonChunk.embedding.cosine_distance(query_vec))
        .limit(top_k)
        .options(selectinload(LessonChunk.lesson))
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())
