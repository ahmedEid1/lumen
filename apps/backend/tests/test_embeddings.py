"""Phase E0 — pgvector + chunker + ingest + retrieval.

These tests run against a real Postgres with pgvector enabled
(``conftest.py`` ``CREATE EXTENSION vector`` + ``Base.metadata.create_all``
materialises the ``lesson_chunks`` table for the suite). The
embedding provider is swapped to ``noop`` per-test so we never
import ``sentence_transformers`` or call OpenAI.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import Course, CourseStatus, Difficulty, Lesson, LessonType, Module, Subject
from app.models.lesson_chunk import EMBEDDING_DIM, LessonChunk
from app.models.user import Role, User
from app.services.embeddings import (
    LocalEmbeddingProvider,
    NoopEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_provider,
)
from app.services.embeddings_ingest import (
    CHUNK_TOKEN_OVERLAP,
    CHUNK_TOKEN_TARGET,
    chunk_lesson,
    ingest_course,
    ingest_lesson,
)
from app.services.embeddings_retrieval import find_relevant_chunks


@pytest.fixture(autouse=True)
def _noop_provider(monkeypatch):
    """All tests in this module run against the deterministic noop provider."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


# ---------- Provider selection ----------


def test_get_provider_respects_env_setting() -> None:
    assert isinstance(get_provider(), NoopEmbeddingProvider)


def test_noop_provider_emits_correct_dim_and_is_deterministic() -> None:
    p = NoopEmbeddingProvider()
    vec_a1 = p.embed(["hello world"])[0]
    vec_a2 = p.embed(["hello world"])[0]
    vec_b = p.embed(["something else"])[0]
    assert len(vec_a1) == EMBEDDING_DIM
    assert vec_a1 == vec_a2
    assert vec_a1 != vec_b


def test_noop_provider_empty_input_short_circuits() -> None:
    assert NoopEmbeddingProvider().embed([]) == []


# ---------- Chunker ----------


def _make_lesson(
    *, title: str = "Lesson", lesson_type: str = "text", body_markdown: str = "",
    data: dict | None = None,
) -> Lesson:
    """Build a non-persisted Lesson for chunker tests."""
    if data is None:
        data = {"type": lesson_type}
        if lesson_type == "text":
            data["body_markdown"] = body_markdown
    return Lesson(
        id=f"lsn_{title[:4]}",
        module_id="mod_x",
        title=title,
        order=0,
        type=LessonType(lesson_type),
        data=data,
    )


def test_chunk_lesson_short_text_returns_one_chunk() -> None:
    lesson = _make_lesson(body_markdown="A short body about transformers.")
    chunks = chunk_lesson(lesson)
    assert len(chunks) == 1
    assert "transformers" in chunks[0]


def test_chunk_lesson_multi_paragraph_text_overlaps() -> None:
    # Build a body ~3x the window target so we get multiple windows.
    paragraph = (
        "Transformers are a type of neural network architecture that has revolutionized "
        "natural language processing tasks. "
    )
    body = " ".join(["Section A. " + paragraph * 60, "Section B. " + paragraph * 60])
    lesson = _make_lesson(body_markdown=body, title="Long Lesson")
    chunks = chunk_lesson(lesson)

    # Expect at least 2 chunks given the body length far exceeds the window.
    assert len(chunks) >= 2

    # No chunk should be radically larger than the target (we use a
    # generous safety margin — ~25% over the word-target because the
    # word/token proxy isn't exact).
    win_words = int(CHUNK_TOKEN_TARGET * 0.75)
    margin = int(win_words * 1.25)
    for c in chunks:
        assert len(c.split()) <= margin

    # Overlap: consecutive chunks share at least one word. Use a small
    # set intersection to confirm the windows aren't cleanly disjoint.
    for a, b in pairwise(chunks):
        a_tail = set(a.split()[-int(CHUNK_TOKEN_OVERLAP * 0.75) :])
        b_head = set(b.split()[: int(CHUNK_TOKEN_OVERLAP * 0.75)])
        assert a_tail & b_head, "consecutive chunks must overlap on at least one word"


def test_chunk_lesson_quiz_concats_question_prompts() -> None:
    lesson = _make_lesson(
        title="Quiz lesson",
        lesson_type="quiz",
        data={
            "type": "quiz",
            "pass_score": 60,
            "questions": [
                {"id": "q1", "prompt": "What is gradient descent?", "kind": "short",
                 "choices": [], "answer_keys": []},
                {"id": "q2", "prompt": "Define overfitting.", "kind": "short",
                 "choices": [], "answer_keys": []},
            ],
        },
    )
    chunks = chunk_lesson(lesson)
    assert len(chunks) == 1
    assert "gradient descent" in chunks[0]
    assert "overfitting" in chunks[0].lower()


def test_chunk_lesson_image_uses_alt_or_falls_back_to_title_only() -> None:
    with_alt = _make_lesson(
        title="Diagram lesson",
        lesson_type="image",
        data={"type": "image", "asset_key": "k", "alt": "A neural-network diagram"},
    )
    assert "neural-network diagram" in chunk_lesson(with_alt)[0]

    without_alt = _make_lesson(
        title="Empty lesson",
        lesson_type="image",
        data={"type": "image", "asset_key": "k", "alt": ""},
    )
    # Only the title remains; one chunk.
    chunks = chunk_lesson(without_alt)
    assert chunks == ["Empty lesson"]


def test_chunk_lesson_empty_text_lesson_returns_no_chunks() -> None:
    # A text lesson with no title (defensive) and no body produces nothing.
    lesson = Lesson(
        id="lsn_empty",
        module_id="mod_x",
        title="",
        order=0,
        type=LessonType.text,
        data={"type": "text", "body_markdown": ""},
    )
    assert chunk_lesson(lesson) == []


# ---------- Ingestion ----------


async def _seed_course_with_lessons(
    db: AsyncSession,
    *,
    bodies: list[str],
) -> Course:
    """Persist a Subject + Course + Module + N text lessons. Returns the Course."""
    owner = User(
        id="usr_owner",
        email="owner@lumen.test",
        password_hash="x",
        full_name="Owner",
        role=Role.instructor,
    )
    subject = Subject(id="subj_x", title="ML", slug=f"ml-{id(bodies)}")
    course = Course(
        id="crs_x",
        owner_id=owner.id,
        subject_id=subject.id,
        title="Test Course",
        slug=f"test-course-{id(bodies)}",
        overview="overview",
        difficulty=Difficulty.beginner,
        status=CourseStatus.draft,
    )
    module = Module(id="mod_x", course_id=course.id, title="Module 1", order=0)
    db.add_all([owner, subject, course, module])
    await db.flush()
    for i, body in enumerate(bodies):
        db.add(
            Lesson(
                id=f"lsn_{i}",
                module_id=module.id,
                title=f"Lesson {i}",
                order=i,
                type=LessonType.text,
                data={"type": "text", "body_markdown": body},
            )
        )
    await db.commit()
    return course


async def test_ingest_lesson_writes_chunks_with_correct_dim(
    db_session: AsyncSession,
) -> None:
    course = await _seed_course_with_lessons(
        db_session,
        bodies=["The mitochondria is the powerhouse of the cell. " * 20],
    )
    res = await db_session.execute(select(Lesson).where(Lesson.module_id == "mod_x"))
    lesson = res.scalar_one()

    written = await ingest_lesson(db_session, lesson, provider=NoopEmbeddingProvider())
    await db_session.commit()
    assert written >= 1

    rows = (
        (await db_session.execute(
            select(LessonChunk).where(LessonChunk.lesson_id == lesson.id)
            .order_by(LessonChunk.chunk_index)
        )).scalars().all()
    )
    assert len(rows) == written
    for i, row in enumerate(rows):
        assert row.chunk_index == i
        assert len(row.embedding) == EMBEDDING_DIM
        assert row.token_count > 0
    # Belt-and-braces: confirm the course parented the lesson cleanly.
    assert course.id == "crs_x"


async def test_ingest_lesson_is_idempotent(db_session: AsyncSession) -> None:
    await _seed_course_with_lessons(
        db_session, bodies=["Re-ingest test body. " * 30]
    )
    res = await db_session.execute(select(Lesson))
    lesson = res.scalars().first()
    assert lesson is not None

    first = await ingest_lesson(db_session, lesson, provider=NoopEmbeddingProvider())
    await db_session.commit()
    again = await ingest_lesson(db_session, lesson, provider=NoopEmbeddingProvider())
    await db_session.commit()

    assert first == again > 0
    # Same count after the second pass — re-ingest deletes the old rows
    # rather than appending duplicates.
    total = (await db_session.execute(
        select(LessonChunk).where(LessonChunk.lesson_id == lesson.id)
    )).scalars().all()
    assert len(total) == again


async def test_ingest_course_walks_every_live_lesson(
    db_session: AsyncSession,
) -> None:
    await _seed_course_with_lessons(
        db_session,
        bodies=[
            "First lesson body about neurons.",
            "Second lesson body about gradients.",
            "Third lesson body about backprop.",
        ],
    )
    total = await ingest_course(db_session, "crs_x")
    assert total >= 3  # at least one chunk per lesson

    rows = (await db_session.execute(select(LessonChunk))).scalars().all()
    assert len(rows) == total
    lesson_ids = {r.lesson_id for r in rows}
    assert len(lesson_ids) == 3


# ---------- Retrieval ----------


async def test_find_relevant_chunks_orders_by_cosine_distance(
    db_session: AsyncSession,
) -> None:
    """The noop provider hashes input → deterministic distinct vectors.

    We seed three lessons whose chunks each get a different vector,
    then verify that querying with the *exact* stored chunk text
    returns that chunk first (cosine distance 0 to itself, > 0 to
    any other).
    """
    await _seed_course_with_lessons(
        db_session,
        bodies=[
            "Alpha document about photosynthesis in plants.",
            "Beta document covering cellular respiration.",
            "Gamma document on DNA replication mechanisms.",
        ],
    )
    await ingest_course(db_session, "crs_x")

    # Pick lesson 1 (Beta) and read back exactly what got stored —
    # the chunker prepends the title, so we have to query with the
    # full stored text to land at cosine distance 0 under the noop
    # provider's exact-text hash.
    stored = (
        await db_session.execute(
            select(LessonChunk).join(Lesson, Lesson.id == LessonChunk.lesson_id)
            .where(Lesson.id == "lsn_1")
        )
    ).scalar_one()

    results = await find_relevant_chunks(
        db_session,
        course_id="crs_x",
        query=stored.text,
        top_k=3,
        provider=NoopEmbeddingProvider(),
    )
    assert len(results) == 3
    # Top hit is the chunk whose embedding matches the query vector exactly.
    assert results[0].id == stored.id
    assert "Beta document" in results[0].text
    # All hits come from the seeded course (course-scope filter works).
    assert {r.lesson.module_id for r in results} == {"mod_x"}


async def test_find_relevant_chunks_respects_top_k(
    db_session: AsyncSession,
) -> None:
    await _seed_course_with_lessons(
        db_session,
        bodies=[
            "Body 1 about topic A.",
            "Body 2 about topic B.",
            "Body 3 about topic C.",
            "Body 4 about topic D.",
        ],
    )
    await ingest_course(db_session, "crs_x")
    results = await find_relevant_chunks(
        db_session, course_id="crs_x", query="topic A", top_k=2,
        provider=NoopEmbeddingProvider(),
    )
    assert len(results) == 2


async def test_find_relevant_chunks_blank_query_returns_empty(
    db_session: AsyncSession,
) -> None:
    assert (
        await find_relevant_chunks(
            db_session, course_id="crs_x", query="   ", top_k=5,
            provider=NoopEmbeddingProvider(),
        )
        == []
    )


# ---------- Provider classes exist (smoke) ----------


def test_provider_classes_have_correct_dim() -> None:
    assert NoopEmbeddingProvider.dim == EMBEDDING_DIM
    assert LocalEmbeddingProvider.dim == EMBEDDING_DIM
    assert OpenAIEmbeddingProvider.dim == EMBEDDING_DIM
