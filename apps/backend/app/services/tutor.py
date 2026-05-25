"""Course-scoped RAG tutor service.

Rebuild Phase E1 / Lumen v2 Phase I2 multi-agent.

The headline UX promise is unchanged from E1:

1. Every answer is grounded in *this course's* content. Not the
   model's training data, not other courses on Lumen — strictly the
   lessons of the course the learner is currently in.
2. Every claim drawn from the context is cited. Citations are
   structured (lesson id + title + excerpt) and the UI renders them
   as clickable lime pills.
3. If retrieval comes back empty, the tutor refuses to answer
   rather than hallucinating from the model's prior. This is the
   guardrail that distinguishes "course tutor" from "chatbot".

**Phase I2 — the orchestrator wrapper.** The single-shot RAG pipeline
that lived here through Phase H now lives split across the
:mod:`tutor_subagents` package (the ``retriever`` is the lifted-out
RAG step) and :mod:`tutor_orchestrator` (the planner + tool dispatch
loop + synthesiser). :func:`ask` is preserved as a thin compatibility
wrapper so the chat API and the MCP ``ask_tutor`` tool keep their
existing signature: they call ``ask(db, course=..., user_message=...,
user_id=..., feature=...)`` and get back a :class:`TutorAnswer`.

Citation parsing + the system-prompt builder are kept here because
the existing tests (and the ``NoopProvider``) pin against them. The
orchestrator's synthesiser uses the same ``[L:<lesson_id>]`` citation
format so :func:`extract_citations` continues to be the canonical
parser when callers want to re-validate citations against a
retrieval set.

That last validation step is the second guardrail: even if the
model hallucinates a citation for a lesson id it never saw, we
drop it on the floor before it reaches the UI. The user can never
click through to a lesson the tutor didn't ground its answer in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.course import Course
from app.models.lesson_chunk import LessonChunk
from app.models.llm_call import SYSTEM_USER_ID
from app.services.embeddings_retrieval import find_relevant_chunks
from app.services.llm import LLMProvider

if TYPE_CHECKING:
    # ``ask_with_trace`` returns ``tuple[TutorAnswer, OrchestratorResult]``.
    # The runtime import is deferred to inside the function body (to
    # break the module-level cycle: tutor_orchestrator imports the
    # tutor sub-agents, which transitively touch this module's types).
    # Without this TYPE_CHECKING import the forward-referenced
    # ``"OrchestratorResult"`` annotation is unresolvable to mypy and
    # ruff, breaking lint on a clean checkout.
    from app.services.tutor_orchestrator import OrchestratorResult

log = get_logger(__name__)


# How much of each chunk's text we put inside the system prompt's
# context block. Long enough to anchor the model on real content;
# short enough that ``top_k=5`` chunks fit comfortably inside the
# context window without crowding the user's question.
CONTEXT_EXCERPT_CHARS = 600
# How much of each chunk's text we surface back to the UI as the
# citation excerpt. Smaller than the prompt excerpt so the pill
# preview stays compact — the full lesson is one click away.
CITATION_EXCERPT_CHARS = 280
# Default retrieval breadth — passed through to
# ``find_relevant_chunks(top_k=...)``. Five is the empirical sweet
# spot Coursera Coach landed on per their published evals; tunable
# without a config flag because it's a single-call argument.
DEFAULT_TOP_K = 5
# Translatable refusal text. The API edge can localise this; the
# service emits English so a downstream caller (a worker, an admin
# tool) gets a predictable string.
REFUSAL_TEXT = (
    "I don't have enough material in this course to answer that. "
    "Try rephrasing, or pick a topic the course actually covers."
)
# Pattern that matches the model's citation tokens. We deliberately
# accept any non-whitespace, non-bracket characters as the lesson
# id so a model that gets the format slightly wrong (extra dots,
# stray punctuation) still parses — the membership check against
# the retrieval set is the real gate.
CITATION_RE = re.compile(r"\[L:([^\s\]]+)\]")


@dataclass(frozen=True)
class Citation:
    """One lesson reference attached to an assistant turn."""

    lesson_id: str
    lesson_title: str
    chunk_excerpt: str

    def to_dict(self) -> dict[str, str]:
        """Serialise to the JSONB shape stored in ``tutor_messages``."""
        return {
            "lesson_id": self.lesson_id,
            "lesson_title": self.lesson_title,
            "chunk_excerpt": self.chunk_excerpt,
        }


@dataclass(frozen=True)
class TutorAnswer:
    """Result of :func:`ask` — the assistant's reply + its citations."""

    answer: str
    citations: list[Citation]
    refused: bool

    def citations_as_dicts(self) -> list[dict[str, str]]:
        return [c.to_dict() for c in self.citations]


def _excerpt(text: str, limit: int) -> str:
    """Trim ``text`` to ``limit`` chars on a word boundary, with ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    # Walk back to the last space so we don't truncate mid-word.
    cut = head.rfind(" ")
    if cut > 0 and cut > limit - 80:
        head = head[:cut]
    return head.rstrip() + "…"


def build_system_prompt(course: Course, chunks: list[LessonChunk]) -> str:
    """Compose the tutor's system prompt for one turn.

    The structure is deliberate:

    1. Persona + scope ("you are the tutor for {course}").
    2. Hard constraint ("answer ONLY from the context below").
    3. Citation format ("wrap each claim with [L:<lesson_id>]").
    4. Refusal fallback ("if the context doesn't cover it, say so").
    5. The retrieval context, one block per chunk, prefixed with
       ``Lesson L<lesson_id>: <title>``.

    The ``Lesson L<id>:`` header is what the model is told to cite,
    and is also what :class:`~app.services.llm.NoopProvider` parses
    back out to generate deterministic test responses.
    """
    blocks: list[str] = []
    for chunk in chunks:
        lesson = chunk.lesson
        title = lesson.title or "Untitled lesson"
        excerpt = _excerpt(chunk.text, CONTEXT_EXCERPT_CHARS)
        blocks.append(f"Lesson L{lesson.id}: {title}\n{excerpt}")
    context_block = "\n\n".join(blocks) if blocks else "(no relevant context found)"

    return (
        f"You are the Lumen course tutor for {course.title}. "
        "Answer ONLY from the course content provided below. If the "
        "context doesn't cover the question, say so honestly and "
        "suggest what topic the course does cover that might be "
        "related.\n\n"
        "Every claim you draw from the context MUST be cited inline "
        "using the format [L:<lesson_id>] (e.g. [L:lsn_abc123]) so "
        "the learner can click through to the source lesson. Do not "
        "invent lesson ids — only cite lessons that appear in the "
        "context below.\n\n"
        "Keep replies concise (a short paragraph or a few bullets). "
        "Plain text, no markdown headings.\n\n"
        "--- Course content ---\n"
        f"{context_block}"
    )


def extract_citations(
    answer: str, chunks: list[LessonChunk]
) -> list[Citation]:
    """Parse ``[L:lesson_id]`` tokens, validate, attach lesson context.

    The retrieval set bounds the citation universe — any token the
    model emits for a lesson id we didn't actually surface is
    silently dropped. This is the second of the two guardrails the
    tutor leans on (the first being "refuse on empty retrieval");
    together they make it impossible for the UI to ever render a
    citation pointing at a lesson the answer wasn't grounded in.

    The output preserves the order of first appearance and
    deduplicates — if the model cites the same lesson three times,
    the UI shows one pill per lesson.
    """
    if not answer:
        return []

    # Build a lookup keyed by lesson id, picking the strongest chunk
    # excerpt per lesson (= the one with the highest retrieval rank,
    # which is the first one we see because the caller passes
    # ``chunks`` in retrieval order).
    by_lesson: dict[str, Citation] = {}
    for chunk in chunks:
        lid = chunk.lesson_id
        if lid in by_lesson:
            continue
        by_lesson[lid] = Citation(
            lesson_id=lid,
            lesson_title=chunk.lesson.title or "Untitled lesson",
            chunk_excerpt=_excerpt(chunk.text, CITATION_EXCERPT_CHARS),
        )

    seen: set[str] = set()
    out: list[Citation] = []
    for match in CITATION_RE.finditer(answer):
        lid = match.group(1)
        if lid in seen:
            continue
        seen.add(lid)
        cite = by_lesson.get(lid)
        if cite is not None:
            out.append(cite)
    return out


async def ask(
    db: AsyncSession,
    *,
    course: Course,
    user_message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    provider: LLMProvider | None = None,
    top_k: int = DEFAULT_TOP_K,
    user_id: str | None = None,
    feature: str = "tutor",
) -> TutorAnswer:
    """Answer ``user_message`` against ``course``'s content with citations.

    Phase I2 — this is now a thin compatibility wrapper around
    :func:`tutor_orchestrator.orchestrate`. The orchestrator runs the
    planner + sub-agent loop + synthesiser; we project its
    :class:`OrchestratorResult` back into a :class:`TutorAnswer` so
    callers (the chat API, the MCP ``ask_tutor`` tool, the eval
    runner) keep their existing signature.

    Two short-circuits before delegation, both preserving the Phase E1
    cost guard:

    1. **Empty question** — return the structured refusal immediately.
       The orchestrator does the same, but doing it here saves one
       function call frame on a hot path.
    2. **Empty retrieval** — when retrieval against the course returns
       nothing, return the refusal *without calling the LLM at all*.
       This is the cost-guard the Phase E1 implementation set up and
       the existing test suite pins. We do the retrieval here once;
       the orchestrator's own retriever sub-agent is wired with
       ``audit=True`` which we *also* want to fire for the multi-agent
       path. Skipping the LLM on empty retrieval is the only place we
       diverge from the orchestrator's "always plan first" behaviour.

    The ``provider`` and ``top_k`` parameters are honoured by the
    short-circuit retrieval but no longer threaded into the
    orchestrator — the orchestrator resolves its provider via
    :func:`llm.get_provider`. Tests that monkeypatch the provider via
    env-vars + cache clear continue to work; tests that hand-pass a
    provider instance are routed only through the short-circuit
    retrieval here and don't reach the orchestrator (no current test
    does this; the parameter is preserved for API compatibility).
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True)

    # Empty-retrieval cost guard — kept here (not deferred into the
    # orchestrator) so a question against an unembedded course doesn't
    # burn a planner round-trip before refusing.
    chunks = await find_relevant_chunks(
        db, course_id=course.id, query=user_message, top_k=top_k
    )
    if not chunks:
        log.info(
            "tutor_refusal_no_retrieval",
            course_id=course.id,
            question_len=len(user_message),
        )
        return TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True)

    # Delegate to the multi-agent orchestrator. Importing at call time
    # avoids the module-level cycle (the orchestrator imports the
    # sub-agents, none of which need anything from this module).
    from app.services.tutor_orchestrator import orchestrate

    result = await orchestrate(
        db,
        user_id=user_id or SYSTEM_USER_ID,
        course=course,
        question=user_message,
        conversation_history=conversation_history,
        feature=feature if feature != "tutor" else "tutor.multi_agent",
    )

    if result.refused:
        return TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True)

    # Resolve lesson-id citations back into the Phase E1 ``Citation``
    # shape (id + title + excerpt) using the chunks we already
    # retrieved above. The orchestrator validates citations against
    # the retriever sub-agent's lesson ids; we project that back to
    # the persistence shape the chat API + MCP already serialise.
    chunk_by_lesson: dict[str, LessonChunk] = {}
    for c in chunks:
        if c.lesson_id not in chunk_by_lesson:
            chunk_by_lesson[c.lesson_id] = c
    citations: list[Citation] = []
    for lid in result.citations:
        chunk = chunk_by_lesson.get(lid)
        if chunk is None:
            continue
        citations.append(
            Citation(
                lesson_id=lid,
                lesson_title=chunk.lesson.title or "Untitled lesson",
                chunk_excerpt=_excerpt(chunk.text, CITATION_EXCERPT_CHARS),
            )
        )

    # Defensive: if the orchestrator's synthesiser produced an answer
    # that didn't cite anything (Noop, or a model that just ignored
    # the citation directive), fall back to the ``extract_citations``
    # parser on the raw text — same as Phase E1.
    if not citations:
        citations = extract_citations(result.answer, chunks)

    log.info(
        "tutor_answered_orchestrator",
        course_id=course.id,
        chunks=len(chunks),
        citations=len(citations),
        tool_calls=len(result.tool_calls_made),
        confidence=result.confidence,
    )
    return TutorAnswer(answer=result.answer, citations=citations, refused=False)


async def ask_with_trace(
    db: AsyncSession,
    *,
    course: Course,
    user_message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    user_id: str | None = None,
    feature: str = "tutor.multi_agent",
) -> tuple[TutorAnswer, OrchestratorResult]:
    """Run the multi-agent orchestrator and project both shapes.

    Phase I2 — surface for callers that want the full orchestrator
    payload (per-turn plan, tool-call log, confidence) alongside the
    legacy :class:`TutorAnswer` shape. The chat API uses this so it
    can render the agent-reasoning panel without making a second
    pass; backward-compatible callers (MCP, evals) continue to use
    :func:`ask` and ignore the orchestrator metadata.

    Returns a tuple ``(TutorAnswer, OrchestratorResult)``. The
    ``TutorAnswer`` exposes the canonical answer + citations + refused
    flag; the ``OrchestratorResult`` exposes ``tool_calls_made`` +
    ``confidence`` + ``root_trace_id`` for the trace surface.

    On the empty-retrieval short-circuit (no chunks in the course),
    returns a refusal :class:`TutorAnswer` plus a synthetic
    :class:`OrchestratorResult` with an empty tool-call list and
    confidence 0 — the chat API surfaces this to the frontend so
    the reasoning panel renders "no plan ran" cleanly.
    """
    # Local import to avoid a module-level cycle.
    from app.services.tutor_orchestrator import (
        OrchestratorResult as _OrchResult,
        orchestrate,
    )

    user_message = (user_message or "").strip()
    if not user_message:
        return (
            TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True),
            _OrchResult(
                answer=REFUSAL_TEXT,
                citations=[],
                tool_calls_made=[],
                confidence=0,
                refused=True,
            ),
        )

    chunks = await find_relevant_chunks(
        db, course_id=course.id, query=user_message, top_k=DEFAULT_TOP_K
    )
    if not chunks:
        log.info(
            "tutor_refusal_no_retrieval",
            course_id=course.id,
            question_len=len(user_message),
        )
        return (
            TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True),
            _OrchResult(
                answer=REFUSAL_TEXT,
                citations=[],
                tool_calls_made=[],
                confidence=0,
                refused=True,
            ),
        )

    orch_result = await orchestrate(
        db,
        user_id=user_id or SYSTEM_USER_ID,
        course=course,
        question=user_message,
        conversation_history=conversation_history,
        feature=feature,
    )

    if orch_result.refused:
        return (
            TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True),
            orch_result,
        )

    chunk_by_lesson: dict[str, LessonChunk] = {}
    for c in chunks:
        if c.lesson_id not in chunk_by_lesson:
            chunk_by_lesson[c.lesson_id] = c
    citations: list[Citation] = []
    for lid in orch_result.citations:
        chunk = chunk_by_lesson.get(lid)
        if chunk is None:
            continue
        citations.append(
            Citation(
                lesson_id=lid,
                lesson_title=chunk.lesson.title or "Untitled lesson",
                chunk_excerpt=_excerpt(chunk.text, CITATION_EXCERPT_CHARS),
            )
        )
    if not citations:
        citations = extract_citations(orch_result.answer, chunks)

    return (
        TutorAnswer(
            answer=orch_result.answer, citations=citations, refused=False
        ),
        orch_result,
    )


__all__ = [
    "CITATION_EXCERPT_CHARS",
    "CITATION_RE",
    "CONTEXT_EXCERPT_CHARS",
    "Citation",
    "DEFAULT_TOP_K",
    "REFUSAL_TEXT",
    "TutorAnswer",
    "ask",
    "ask_with_trace",
    "build_system_prompt",
    "extract_citations",
]
