"""Chunk-then-embed ingestion pipeline.

Rebuild Phase E0. Takes a Lesson (or every live Lesson in a Course)
and produces / refreshes the ``lesson_chunks`` rows that the RAG
tutor and downstream AI surfaces consume.

Chunking strategy: ~500-token sliding window with 50-token overlap.
We use a cheap word-count proxy for "tokens" (split on whitespace and
multiply by 1.3) because the real tokenizer ships with the embedding
model and we want to keep the chunker independent of the provider —
the alternative is loading the tokenizer here too which defeats the
deferred-import contract in :mod:`app.services.embeddings`. The
proxy over-estimates slightly, which keeps us safely under any
model's hard limit.

Non-text lesson types: we still produce *one* chunk for them so the
retriever has something to point at. The chunk text combines the
lesson title with whatever human-readable fields exist in
``lesson.data``:

* ``text``    → ``body_markdown``
* ``video``   → ``url`` (link metadata only — we don't transcribe; that
                lands in Phase E3)
* ``image``   → ``alt`` text
* ``file``    → ``filename``
* ``quiz``    → every question's ``prompt`` joined into one document

Idempotency: :func:`ingest_lesson` deletes the lesson's existing
chunks before inserting new ones. Re-running the task is safe; a
publish that fires twice in a row produces the same row count as one
publish.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.course import Course, Lesson, Module
from app.models.lesson_chunk import LessonChunk
from app.services.embeddings import EmbeddingProvider, get_provider

if TYPE_CHECKING:  # pragma: no cover
    pass

log = get_logger(__name__)


# Target window size, in approximate tokens. Tunable — see module
# docstring for why we use a proxy rather than a real tokenizer.
CHUNK_TOKEN_TARGET: int = 500
CHUNK_TOKEN_OVERLAP: int = 50
_WORDS_PER_TOKEN: float = 0.75  # ~1.3 tokens/word → invert for words/token


def _approx_token_count(text: str) -> int:
    """Cheap token estimate — overshoots for safety."""
    words = max(1, len(text.split()))
    # ceil(words / words_per_token)
    return int(words / _WORDS_PER_TOKEN) + (1 if words % 1 else 0)


def _lesson_source_text(lesson: Lesson) -> str:
    """Pull the embeddable text out of a Lesson regardless of type.

    Returns "" if there's truly nothing to embed (e.g. an image with no
    alt text); the caller skips empty source text so we don't write
    zero-information chunks.
    """
    data: dict[str, Any] = dict(lesson.data or {})
    parts: list[str] = [lesson.title]
    lesson_type = str(lesson.type)

    if lesson_type == "text":
        if md := data.get("body_markdown"):
            parts.append(str(md))
    elif lesson_type == "quiz":
        for q in data.get("questions") or []:
            if prompt := q.get("prompt"):
                parts.append(str(prompt))
    elif lesson_type == "image":
        if alt := data.get("alt"):
            parts.append(str(alt))
    elif lesson_type == "file":
        if filename := data.get("filename"):
            parts.append(str(filename))
    elif lesson_type == "video" and (desc := data.get("description")):
        # For video we lean on the description if the editor included
        # one (the schema doesn't require it, but instructors often
        # add context in the title); we'll get real transcripts via
        # Phase E3 once the multi-modal ingest pipeline lands.
        parts.append(str(desc))

    return "\n\n".join(p for p in parts if p).strip()


def chunk_lesson(lesson: Lesson) -> list[str]:
    """Split a lesson's source text into ~500-token overlapping windows.

    Returns ``[]`` if the lesson has no embeddable content. The
    overlap ensures that a query whose semantically-relevant phrase
    straddles two windows still hits at least one chunk that contains
    it whole.
    """
    text = _lesson_source_text(lesson)
    if not text:
        return []

    words = text.split()
    if not words:
        return []

    # Convert the token targets into word counts using the same proxy
    # the cost-estimator uses, so a "500-token chunk" really is ~500
    # tokens on a real tokenizer.
    win_words = max(1, int(CHUNK_TOKEN_TARGET * _WORDS_PER_TOKEN))
    overlap_words = max(0, int(CHUNK_TOKEN_OVERLAP * _WORDS_PER_TOKEN))
    step = max(1, win_words - overlap_words)

    chunks: list[str] = []
    i = 0
    while i < len(words):
        window = words[i : i + win_words]
        chunks.append(" ".join(window))
        if i + win_words >= len(words):
            break
        i += step
    return chunks


async def ingest_lesson(
    db: AsyncSession,
    lesson: Lesson,
    *,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Chunk + embed + persist one lesson. Returns the number of chunks written.

    Idempotent: deletes any existing chunks for this lesson before
    inserting new ones, so a publish that triggers re-ingest doesn't
    leave stale rows around.
    """
    chunks = chunk_lesson(lesson)
    # Always purge first — even if the new chunk list is empty, the
    # old ones must go (e.g. an instructor cleared a text lesson's
    # body).
    await db.execute(delete(LessonChunk).where(LessonChunk.lesson_id == lesson.id))
    if not chunks:
        return 0

    prov = provider or get_provider()
    vectors = prov.embed(chunks)
    if len(vectors) != len(chunks):  # pragma: no cover — defensive
        raise RuntimeError(
            f"Embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks"
        )

    # Stamp the per-chunk embedding provenance (ADR-0029 §D6 / FR-EMBED-03) from
    # the resolving provider — getattr-defensive so a provider stub without
    # ``model_id`` (legacy/test double) doesn't break ingest; the columns are
    # nullable until migration 0043 tightens them.
    model_id = getattr(prov, "model_id", None)
    dim = getattr(prov, "dim", None)
    rows = [
        LessonChunk(
            id=new_id(),
            lesson_id=lesson.id,
            chunk_index=i,
            text=text,
            embedding=vec,
            token_count=_approx_token_count(text),
            embedding_model=model_id,
            embedding_dim=dim,
        )
        for i, (text, vec) in enumerate(zip(chunks, vectors, strict=True))
    ]
    db.add_all(rows)
    await db.flush()
    log.info(
        "lesson_chunks_indexed",
        lesson_id=lesson.id,
        chunks=len(rows),
    )
    return len(rows)


async def ingest_course(
    db: AsyncSession,
    course_id: str,
    *,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Re-ingest every live lesson in a course. Returns total chunks written."""
    res = await db.execute(
        select(Course)
        .where(Course.id == course_id, Course.deleted_at.is_(None))
        .options(selectinload(Course.modules).selectinload(Module.lessons))
    )
    course = res.scalar_one_or_none()
    if course is None:
        log.info("ingest_course_skipped_missing", course_id=course_id)
        return 0

    prov = provider or get_provider()
    total = 0
    for module in course.modules:
        for lesson in module.lessons:
            if lesson.deleted_at is not None:
                continue
            total += await ingest_lesson(db, lesson, provider=prov)
    await db.commit()
    log.info("course_indexed", course_id=course_id, total_chunks=total)
    return total
