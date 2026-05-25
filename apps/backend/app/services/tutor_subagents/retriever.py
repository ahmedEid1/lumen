"""Retriever sub-agent — course-scoped RAG over ``lesson_chunks``.

Lumen v2 Phase I2. The planner's most-frequently-dispatched tool: a
straight wrap around :func:`find_relevant_chunks` (Phase E0) with
``audit=True`` so the H7 retrieval-audit table captures the query +
top-K chunks + similarity scores.

No LLM call here — this is pure retrieval. The synthesiser at the
end of the orchestrator loop will fold the chunks into its prompt
and produce the final cited answer.

Returns a :class:`RetrieverResult` carrying:

* ``chunks`` — list of ``RetrieverChunk`` records (lesson id + title
  + excerpt + similarity score). Ordered most-similar-first, same as
  the underlying ``find_relevant_chunks`` ordering.
* ``citations`` — deduplicated lesson ids in retrieval order. The
  synthesiser uses these to know which ``[L:<id>]`` tokens are
  legal to emit.
* ``note`` — short human-readable status string ("found 4 chunks",
  "no relevant content"). Surfaced to the frontend's reasoning
  panel so a recruiter watching the trace sees what happened.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_OK
from app.models.course import Course
from app.services import agent_tracer
from app.services.embeddings_retrieval import find_relevant_chunks

log = get_logger(__name__)

# Excerpt length surfaced in the trace + serialised into the
# synthesiser's prompt. Long enough to anchor the model, short
# enough that 6 chunks fit comfortably in the prompt budget.
EXCERPT_CHARS = 600


class RetrieverChunk(BaseModel):
    """One chunk surfaced to the synthesiser."""

    model_config = ConfigDict(frozen=True)

    lesson_id: str
    lesson_title: str
    text: str
    score: float = Field(description="pgvector cosine distance (lower = more similar).")


class RetrieverResult(BaseModel):
    """Output of the retriever sub-agent."""

    model_config = ConfigDict(frozen=True)

    chunks: list[RetrieverChunk] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    note: str = ""


async def run(
    db: AsyncSession,
    *,
    course: Course,
    query: str,
    user_id: str,
    top_k: int = 6,
    feature: str = "tutor.multi_agent",
    step_index: int = 0,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
) -> RetrieverResult:
    """Dispatch the retriever over ``course`` for ``query``.

    Writes one ``agent_traces`` row with ``step="sub_agent.retriever"``
    summarising the result. The underlying retrieval helper writes its
    own ``retrieval_audits`` row (because we pass ``audit=True``), so
    the admin observability surface gets both a coarse trace step and
    a fine-grained retrieval audit.
    """
    chunks_orm = await find_relevant_chunks(
        db,
        course_id=course.id,
        query=query,
        top_k=top_k,
        audit=True,
        audit_user_id=user_id,
        audit_feature=feature,
    )
    # ``find_relevant_chunks`` returns ORM rows; pull the score off the
    # audit-aware path by re-projecting via the convenience tuple shape
    # — but the audited helper currently discards scores at the public
    # boundary. We re-derive an approximate "rank-as-score" so the
    # frontend has a number to render; the real cosine distances land
    # in the ``retrieval_audits`` row.
    chunks: list[RetrieverChunk] = []
    citations: list[str] = []
    seen_lessons: set[str] = set()
    for rank, c in enumerate(chunks_orm):
        excerpt = (c.text or "").strip()
        if len(excerpt) > EXCERPT_CHARS:
            excerpt = excerpt[:EXCERPT_CHARS].rstrip() + "…"
        title = (c.lesson.title or "Untitled lesson") if c.lesson else "Untitled lesson"
        chunks.append(
            RetrieverChunk(
                lesson_id=c.lesson_id,
                lesson_title=title,
                text=excerpt,
                # Rank-as-distance proxy: 0.0 best, 1.0 worst — purely
                # for display ordering in the frontend trace panel.
                # Real similarity scores live in ``retrieval_audits``.
                score=round(rank / max(1, len(chunks_orm)), 3),
            )
        )
        if c.lesson_id not in seen_lessons:
            seen_lessons.add(c.lesson_id)
            citations.append(c.lesson_id)

    note = (
        f"found {len(chunks)} chunk(s) across {len(citations)} lesson(s)"
        if chunks
        else "no relevant content in this course"
    )

    await agent_tracer.record_step(
        db,
        user_id=user_id,
        feature=feature,
        step="sub_agent.retriever",
        step_index=step_index,
        parent_trace_id=parent_trace_id,
        parent_call_id=parent_call_id,
        payload={
            "args": {"query": query[:240], "top_k": top_k},
            "result_summary": {
                "chunk_count": len(chunks),
                "lesson_count": len(citations),
                "note": note,
            },
        },
        status=TRACE_STATUS_OK,
    )

    return RetrieverResult(chunks=chunks, citations=citations, note=note)


__all__ = ["RetrieverChunk", "RetrieverResult", "run"]
