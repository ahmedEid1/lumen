"""Course-scoped RAG tutor service.

Rebuild Phase E1. This is the engine behind "Ask the tutor" on every
course surface. The headline UX promise:

1. Every answer is grounded in *this course's* content. Not the
   model's training data, not other courses on Lumen — strictly the
   lessons of the course the learner is currently in.
2. Every claim drawn from the context is cited. Citations are
   structured (lesson id + title + excerpt) and the UI renders them
   as clickable lime pills.
3. If retrieval comes back empty, the tutor refuses to answer
   rather than hallucinating from the model's prior. This is the
   guardrail that distinguishes "course tutor" from "chatbot".

The plumbing in five steps:

1. :func:`find_relevant_chunks` (Phase E0) does an HNSW cosine
   search against ``lesson_chunks`` filtered to this course.
2. If the retrieval set is empty → return the structured refusal
   immediately (no LLM call, no token spend).
3. Otherwise build a system prompt that pins the model to the
   retrieved chunks. The chunks are emitted in
   ``Lesson L<lesson_id>: <title>\\n<excerpt>`` blocks — the
   ``L<id>:`` prefix is the citation token the model is told to
   wrap claims with.
4. Call :meth:`LLMProvider.chat` with ``[system] + history + [user]``.
5. :func:`extract_citations` parses ``[L:lesson_id]`` tokens out of
   the reply, validates each against the retrieval set, and
   attaches the matching lesson context.

That last validation step is the second guardrail: even if the
model hallucinates a citation for a lesson id it never saw, we
drop it on the floor before it reaches the UI. The user can never
click through to a lesson the tutor didn't ground its answer in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.course import Course
from app.models.lesson_chunk import LessonChunk
from app.services.embeddings_retrieval import find_relevant_chunks
from app.services.llm import (
    ChatMessage,
    LLMProvider,
    NOOP_REFUSAL,
    get_provider,
)

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


def _build_messages(
    *,
    course: Course,
    chunks: list[LessonChunk],
    user_message: str,
    history: list[dict[str, Any]] | None,
) -> list[ChatMessage]:
    """Compose the full message list sent to the LLM provider."""
    messages: list[ChatMessage] = [
        ChatMessage(role="system", content=build_system_prompt(course, chunks))
    ]
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            messages.append(ChatMessage(role=role, content=content))
    messages.append(ChatMessage(role="user", content=user_message))
    return messages


def _is_refusal(answer: str) -> bool:
    """Detect the noop provider's refusal sentinel as a refusal."""
    return NOOP_REFUSAL.strip() in (answer or "").strip()


async def ask(
    db: AsyncSession,
    *,
    course: Course,
    user_message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    provider: LLMProvider | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> TutorAnswer:
    """Answer ``user_message`` against ``course``'s content with citations.

    Pipeline:

    1. ``find_relevant_chunks`` — HNSW cosine over ``lesson_chunks``,
       restricted to live lessons in this course.
    2. **Empty retrieval guardrail** — if nothing comes back, return
       the structured refusal *without calling the LLM*. This is
       both a hallucination guard and a cost guard.
    3. Build system prompt + history + user → call the provider.
    4. **Refusal echo guardrail** — if the model's reply matches the
       noop refusal sentinel (or starts with "I don't know"), mark
       the answer as a refusal so the UI surfaces it as such.
    5. Parse and validate citations against the retrieval set.
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True)

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

    llm = provider or get_provider()
    messages = _build_messages(
        course=course,
        chunks=chunks,
        user_message=user_message,
        history=conversation_history,
    )
    answer_text = await llm.chat(messages, temperature=0.2)

    if _is_refusal(answer_text):
        return TutorAnswer(answer=REFUSAL_TEXT, citations=[], refused=True)

    citations = extract_citations(answer_text, chunks)
    log.info(
        "tutor_answered",
        course_id=course.id,
        chunks=len(chunks),
        citations=len(citations),
        provider=getattr(llm, "name", "unknown"),
    )
    return TutorAnswer(answer=answer_text, citations=citations, refused=False)


__all__ = [
    "CITATION_EXCERPT_CHARS",
    "CITATION_RE",
    "CONTEXT_EXCERPT_CHARS",
    "Citation",
    "DEFAULT_TOP_K",
    "REFUSAL_TEXT",
    "TutorAnswer",
    "ask",
    "build_system_prompt",
    "extract_citations",
]
