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
from app.models.course import Course, Lesson, Module
from app.models.lesson_chunk import LessonChunk
from app.models.llm_call import SYSTEM_USER_ID
from app.models.retrieval_audit import (
    MAX_CHUNKS_PER_AUDIT,
    SNIPPET_MAX_CHARS,
    RetrievalAudit,
)
from app.services.embeddings import EmbeddingProvider, get_provider
from app.services.visibility import retrieval_acl_clause

log = get_logger(__name__)


async def find_relevant_chunks(
    db: AsyncSession,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    viewer: str | None = None,
    enforce_acl: bool = True,
    provider: EmbeddingProvider | None = None,
    audit: bool = False,
    audit_user_id: str | None = None,
    audit_feature: str = "tutor",
) -> list[LessonChunk]:
    """Return the ``top_k`` chunks most semantically similar to ``query``.

    Restricted to live lessons inside ``course_id`` — soft-deleted
    lessons (``Lesson.deleted_at IS NOT NULL``) are filtered out, and
    chunks belonging to lessons in other courses are unreachable.

    **Data-level ACL (PR-22 / ADR-0029 §D3-D4).** When ``enforce_acl=True``
    (default) the query additionally JOINs ``Course`` (reachable via
    ``Module.course_id``) and ANDs ``retrieval_acl_clause(viewer)`` —
    defense-in-depth so the SQL cannot return another user's private chunk
    even if a caller forgets the course-level authorizer. ``viewer`` is the
    requesting user's id (``None`` = anonymous/system → publicly-listed only).

    ``enforce_acl=False`` is reserved for the owner-proven inline-index
    fallback (ownership already established by ``can_view_course``) and the
    eval harness; a CI grep-guard (``test_no_unallowlisted_enforce_acl_false``)
    forbids new ``enforce_acl=False`` sites outside the allowlist.

    When ``audit=True``, after the retrieval succeeds we also write a
    ``retrieval_audits`` row (best-effort, SAVEPOINT-isolated).
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
        stmt = _apply_acl(stmt, enforce_acl=enforce_acl, viewer=viewer)
        rows = (await db.execute(stmt)).all()
        chunks_with_scores: list[tuple[LessonChunk, float]] = [(r[0], float(r[1])) for r in rows]
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
    stmt = _apply_acl(stmt, enforce_acl=enforce_acl, viewer=viewer)
    res = await db.execute(stmt)
    return list(res.scalars().all())


def _apply_acl(stmt, *, enforce_acl: bool, viewer: str | None):
    """JOIN ``Course`` + AND the central retrieval ACL when enforcing (PR-22).

    The course-scoped SELECTs already filter ``Module.course_id``, so the JOIN
    to the single target course's row is cheap (index-covered by
    ``ix_courses_listed``). The clause is redundant-by-design with the
    caller's ``can_view_course`` gate for per-course retrieval (R-U4 leak test
    pins it) and IS the boundary for any caller that forgot it.
    """
    if not enforce_acl:
        return stmt
    return stmt.join(Course, Course.id == Module.course_id).where(retrieval_acl_clause(viewer))


async def find_relevant_chunks_inline_fallback(
    db: AsyncSession,
    *,
    course_id: str,
    query: str,
    top_k: int = 5,
    provider: EmbeddingProvider | None = None,
) -> list[LessonChunk]:
    """Owner-proven inline-index fallback (R-U2′ / ADR-0029 §D8.3, PR-22).

    The **only** legitimate ``enforce_acl=False`` site. When a viewable course
    has live lessons but zero chunks (no worker in dev, or first tutor turn on
    a fresh private course), the tutor calls this AFTER ``can_view_course`` has
    already proven the caller may see the course — so the data-level ACL is
    redundant and we skip it (it would otherwise require the viewer id we no
    longer need). It indexes the ``index_inline_top_n`` most-recently-updated
    live lessons (bounded best-effort) then retrieves over whatever now exists.

    Ownership/visibility MUST be established by the caller first; this helper
    does not re-check it. The single ``enforce_acl=False`` call below is what
    ``test_no_unallowlisted_enforce_acl_false`` allowlists.
    """
    from app.core.config import get_settings
    from app.services.embeddings_ingest import ingest_lesson

    settings = get_settings()
    top_n = max(1, int(getattr(settings, "index_inline_top_n", 5)))

    # The N most-recently-updated live lessons of this (owner-proven) course.
    lesson_stmt = (
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course_id, Lesson.deleted_at.is_(None))
        .order_by(Lesson.updated_at.desc())
        .limit(top_n)
    )
    lessons = list((await db.execute(lesson_stmt)).scalars().all())
    prov = provider or get_provider()
    for lesson in lessons:
        try:
            await ingest_lesson(db, lesson, provider=prov)
        except Exception:  # pragma: no cover — best-effort, never block the turn
            log.warning("inline_index_lesson_failed", lesson_id=lesson.id)
    await db.commit()

    # Retrieve over whatever now exists. ACL is intentionally NOT enforced here
    # (ownership already proven upstream) — the single allowlisted bypass.
    return await find_relevant_chunks(
        db,
        course_id=course_id,
        query=query,
        top_k=top_k,
        enforce_acl=False,  # noqa: enforce-acl — owner-proven inline-index fallback (R-U2′)
        provider=prov,
    )


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
