"""``find_relevant_chunks(audit=True)`` writes a ``retrieval_audits`` row.

Lumen v2 Phase H7. The retriever's audit side-channel is opt-in;
existing call sites (the tutor) keep the default ``audit=False``
and don't write rows. With ``audit=True``, one row lands per
retrieval, carrying the query, the top-K chunks, and their cosine
distance scores.

We seed a small course with three lessons + chunks and exercise
both the audit and the no-audit paths. The noop embedding provider
keeps the tests deterministic and free of network calls.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    ModerationState,
    Module,
    Subject,
    Visibility,
)
from app.models.lesson_chunk import LessonChunk
from app.models.retrieval_audit import RetrievalAudit
from app.models.user import Role, User
from app.services.embeddings import NoopEmbeddingProvider
from app.services.embeddings_ingest import ingest_course
from app.services.embeddings_retrieval import find_relevant_chunks


@pytest.fixture(autouse=True)
def _noop_provider(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _seed_course(db: AsyncSession, *, suffix: str) -> str:
    """Persist a Subject + Course + Module + 3 text lessons. Returns course_id.

    Each test gets a unique ``suffix`` so the seeded ids and slugs
    don't collide with other tests in the same session (the test
    DB isn't truncated between every test — see ``conftest.py``).
    """
    owner = User(
        id=f"usr_{suffix}",
        email=f"owner-{suffix}@lumen.test",
        password_hash="x",
        full_name="Owner",
        role=Role.instructor,
    )
    subject = Subject(id=f"subj_{suffix}", title="ML", slug=f"ml-{suffix}")
    course_id = f"crs_{suffix}"
    course = Course(
        id=course_id,
        owner_id=owner.id,
        subject_id=subject.id,
        title="Audit Test Course",
        slug=f"audit-test-{suffix}",
        overview="overview",
        difficulty=Difficulty.beginner,
        # S2 / ADR-0029: ``find_relevant_chunks`` now ANDs the retrieval ACL.
        # These audit tests call it without a ``viewer`` (→ None → publicly
        # listed only), so the course must be public + published +
        # moderation-approved for its chunks to be retrievable. The audit
        # behaviour under test is orthogonal to visibility.
        status=CourseStatus.published,
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
    )
    module = Module(id=f"mod_{suffix}", course_id=course.id, title="Module 1", order=0)
    db.add_all([owner, subject, course, module])
    await db.flush()
    for i, body in enumerate(
        [
            "Alpha document about photosynthesis in plants.",
            "Beta document covering cellular respiration.",
            "Gamma document on DNA replication mechanisms.",
        ]
    ):
        db.add(
            Lesson(
                id=f"lsn_{suffix}_{i}",
                module_id=module.id,
                title=f"Lesson {i}",
                order=i,
                type=LessonType.text,
                data={"type": "text", "body_markdown": body},
            )
        )
    await db.commit()
    return course_id


# ---------- audit=False (default — no row written) ----------


async def test_default_does_not_write_audit_row(db_session: AsyncSession) -> None:
    suffix = uuid.uuid4().hex[:8]
    course_id = await _seed_course(db_session, suffix=suffix)
    await ingest_course(db_session, course_id)
    await db_session.commit()

    # Capture the audit row count for *this user* before the call
    # so other parallel tests don't make the count noisy.
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    before = (
        (await db_session.execute(select(RetrievalAudit).where(RetrievalAudit.user_id == user_id)))
        .scalars()
        .all()
    )
    assert before == []

    results = await find_relevant_chunks(
        db_session,
        course_id=course_id,
        query="photosynthesis",
        top_k=3,
        provider=NoopEmbeddingProvider(),
        # audit defaults to False — explicit here for clarity.
        audit=False,
        audit_user_id=user_id,
    )
    assert len(results) > 0

    after = (
        (await db_session.execute(select(RetrievalAudit).where(RetrievalAudit.user_id == user_id)))
        .scalars()
        .all()
    )
    assert after == []


# ---------- audit=True (writes one row) ----------


async def test_audit_true_writes_row_with_chunks_and_scores(
    db_session: AsyncSession,
) -> None:
    """``audit=True`` → one ``retrieval_audits`` row with the top-K chunks."""
    suffix = uuid.uuid4().hex[:8]
    course_id = await _seed_course(db_session, suffix=suffix)
    await ingest_course(db_session, course_id)
    await db_session.commit()

    user_id = f"u-{uuid.uuid4().hex[:16]}"
    results = await find_relevant_chunks(
        db_session,
        course_id=course_id,
        query="cellular respiration",
        top_k=3,
        provider=NoopEmbeddingProvider(),
        audit=True,
        audit_user_id=user_id,
        audit_feature="tutor",
    )
    await db_session.commit()
    assert len(results) > 0

    audit = (
        await db_session.execute(select(RetrievalAudit).where(RetrievalAudit.user_id == user_id))
    ).scalar_one()
    assert audit.query == "cellular respiration"
    assert audit.course_id == course_id
    assert audit.feature == "tutor"
    assert isinstance(audit.chunks, list)
    assert 1 <= len(audit.chunks) <= 3

    # Each chunk has the keys the dashboard expects.
    for c in audit.chunks:
        assert set(c.keys()) >= {"chunk_id", "lesson_id", "score", "snippet"}
        assert isinstance(c["score"], (int, float))
        # Snippet capped at 120 chars per the model constant.
        assert len(c["snippet"]) <= 120

    # ``top_score`` matches the first chunk's score (retrieval is
    # ordered ascending by cosine distance, lower = more similar).
    assert audit.top_score == audit.chunks[0]["score"]
    # Scores are non-decreasing across the list.
    for prev, curr in zip(audit.chunks, audit.chunks[1:], strict=False):
        assert prev["score"] <= curr["score"]


async def test_audit_chunks_reference_real_lesson_chunks(
    db_session: AsyncSession,
) -> None:
    """Each captured chunk_id must point at a real ``lesson_chunks`` row."""
    suffix = uuid.uuid4().hex[:8]
    course_id = await _seed_course(db_session, suffix=suffix)
    await ingest_course(db_session, course_id)
    await db_session.commit()

    user_id = f"u-{uuid.uuid4().hex[:16]}"
    await find_relevant_chunks(
        db_session,
        course_id=course_id,
        query="DNA replication",
        top_k=2,
        provider=NoopEmbeddingProvider(),
        audit=True,
        audit_user_id=user_id,
    )
    await db_session.commit()

    audit = (
        await db_session.execute(select(RetrievalAudit).where(RetrievalAudit.user_id == user_id))
    ).scalar_one()
    for chunk_meta in audit.chunks:
        row = (
            await db_session.execute(
                select(LessonChunk).where(LessonChunk.id == chunk_meta["chunk_id"])
            )
        ).scalar_one()
        assert row.lesson_id == chunk_meta["lesson_id"]


async def test_audit_blank_query_writes_no_row(db_session: AsyncSession) -> None:
    """A blank query short-circuits to an empty result — no audit row."""
    suffix = uuid.uuid4().hex[:8]
    course_id = await _seed_course(db_session, suffix=suffix)
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    results = await find_relevant_chunks(
        db_session,
        course_id=course_id,
        query="   ",
        top_k=3,
        provider=NoopEmbeddingProvider(),
        audit=True,
        audit_user_id=user_id,
    )
    assert results == []
    rows = (
        (await db_session.execute(select(RetrievalAudit).where(RetrievalAudit.user_id == user_id)))
        .scalars()
        .all()
    )
    assert rows == []
