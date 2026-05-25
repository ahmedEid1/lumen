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

Phase H7 adds an opt-in ``audit=True`` parameter that, alongside the
return value, also writes one ``retrieval_audits`` row capturing
the query, the chunks retrieved, and their similarity scores. The
default (``audit=False``) leaves the table untouched so existing
call sites — including the tutor — don't change behaviour. I2's
multi-agent tutor will flip the flag on at its call site once it
lands; this module just provides the hook.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.models.course import Lesson, Module
from app.models.lesson_chunk import LessonChunk
from app.models.llm_call import SYSTEM_USER_ID
from app.models.retrieval_audit import (
    MAX_CHUNKS_PER_AUDIT,
    SNIPPET_MAX_CHARS,
    RetrievalAudit,
)
from app.services.embeddings import EmbeddingProvider, get_provider

log = get_logger(__name__)


async def find_relevant_chunks(
    db: AsyncSession,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    provider: EmbeddingProvider | None = None,
    audit: bool = False,
    audit_user_id: str | None = None,
    audit_feature: str = "tutor",
) -> list[LessonChunk]:
    """Return the ``top_k`` chunks most semantically similar to ``query``.

    Restricted to live lessons inside ``course_id`` — soft-deleted
    lessons (``Lesson.deleted_at IS NOT NULL``) are filtered out, and
    chunks belonging to lessons in other courses are unreachable. The
    caller is responsible for any further authz check (e.g. "is the
    asker enrolled or the owner?") — this helper is data-layer only.

    When ``audit=True``, after the retrieval succeeds we also write
    a ``retrieval_audits`` row capturing the query + top-K chunks +
    their cosine-distance scores. The write is best-effort and
    SAVEPOINT-isolated — a hiccup persisting the audit row will not
    fail the retrieval. ``audit_user_id`` defaults to the
    ``"__system__"`` sentinel for callers that haven't threaded a
    user id through (e.g. eval suites); ``audit_feature`` defaults
    to ``"tutor"`` because that's the only existing caller, but
    future surfaces (learning-path planner, etc.) should pass their
    own slug.
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
    distance_col = LessonChunk.embedding.cosine_distance(query_vec)
    if audit:
        # When auditing we need the distance score alongside each
        # chunk. Two queries (one for the scored top-K, one for the
        # eager-loaded chunks) would burn an extra round-trip; we
        # instead select ``(LessonChunk, distance)`` rows together.
        # ``selectinload`` on the relationship still triggers the
        # follow-up SELECT for the eager Lesson load.
        stmt = (
            select(LessonChunk, distance_col.label("distance"))
            .join(Lesson, Lesson.id == LessonChunk.lesson_id)
            .join(Module, Module.id == Lesson.module_id)
            .where(
                Module.course_id == course_id,
                Lesson.deleted_at.is_(None),
            )
            .order_by(distance_col)
            .limit(top_k)
            .options(selectinload(LessonChunk.lesson))
        )
        rows = (await db.execute(stmt)).all()
        chunks_with_scores: list[tuple[LessonChunk, float]] = [
            (r[0], float(r[1])) for r in rows
        ]
        chunks = [c for c, _ in chunks_with_scores]

        await _persist_audit(
            db,
            query=query,
            course_id=course_id,
            user_id=audit_user_id or SYSTEM_USER_ID,
            feature=audit_feature,
            chunks_with_scores=chunks_with_scores,
        )
        return chunks

    stmt = (
        select(LessonChunk)
        .join(Lesson, Lesson.id == LessonChunk.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .where(
            Module.course_id == course_id,
            Lesson.deleted_at.is_(None),
        )
        .order_by(distance_col)
        .limit(top_k)
        .options(selectinload(LessonChunk.lesson))
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def _persist_audit(
    db: AsyncSession,
    *,
    query: str,
    course_id: str | None,
    user_id: str,
    feature: str,
    chunks_with_scores: list[tuple[LessonChunk, float]],
) -> None:
    """Write one ``retrieval_audits`` row. Best-effort, savepoint-isolated.

    Mirrors the H1 cost-meter pattern: a passive observability
    write must never fail the request it's observing. We swallow
    ``SQLAlchemyError`` and log at WARNING; the retrieval result
    is already in the caller's hands at this point.
    """
    truncated = chunks_with_scores[:MAX_CHUNKS_PER_AUDIT]
    chunks_json = [
        {
            "chunk_id": c.id,
            "lesson_id": c.lesson_id,
            "score": score,
            "snippet": (c.text or "")[:SNIPPET_MAX_CHARS],
        }
        for c, score in truncated
    ]
    top_score = chunks_json[0]["score"] if chunks_json else None

    try:
        async with db.begin_nested():
            row = RetrievalAudit(
                user_id=user_id,
                feature=feature,
                query=query,
                course_id=course_id,
                chunks=chunks_json,
                top_score=top_score,
            )
            db.add(row)
            await db.flush()
    except SQLAlchemyError:
        log.exception(
            "retrieval_audit_persist_failed",
            user_id=user_id,
            feature=feature,
            course_id=course_id,
        )
