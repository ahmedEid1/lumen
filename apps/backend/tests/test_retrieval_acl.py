"""S2.8a (PR-22) — per-course RAG retrieval ACL in find_relevant_chunks.

Structural (pure-unit): the helper exposes ``viewer`` + ``enforce_acl`` and the
inline fallback is the single ``enforce_acl=False`` site.

DB-backed (runs under ``make test.api``): the leak tests — a private non-owner
course's chunks are NEVER returned; the owner gets their own private course's
chunks; the owner's build_failed / soft-deleted drafts are excluded (R-S12);
``enforce_acl=False`` is the single bypass.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import CourseStatus, ModerationState, Visibility
from app.services import embeddings_retrieval as er


@pytest.fixture(autouse=True)
def _noop_providers(monkeypatch):
    """Force the noop embedding provider so query-time ``prov.embed`` never
    imports ``sentence_transformers`` (absent in CI — torch is dev-image-only;
    same dodge as test_tutor_idor.py). The chunk fixtures already use literal
    vectors; ranking is irrelevant to these leak tests."""
    from app.core.config import get_settings

    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Structural
# --------------------------------------------------------------------------


def test_find_relevant_chunks_has_acl_params():
    sig = inspect.signature(er.find_relevant_chunks)
    assert "viewer" in sig.parameters
    assert "enforce_acl" in sig.parameters
    assert sig.parameters["enforce_acl"].default is True  # secure by default


def test_inline_fallback_exists():
    assert hasattr(er, "find_relevant_chunks_inline_fallback")


# --------------------------------------------------------------------------
# DB-backed leak tests
# --------------------------------------------------------------------------


async def _owner(db):
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    u = User(
        email=f"o-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="O",
        role=Role.instructor,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _course_with_chunk(db, owner, *, visibility, status, moderation_state, deleted=False):
    """Create a course with one module + lesson + a lesson chunk."""
    from datetime import UTC, datetime

    from app.models.course import Course, LessonType, Module, Subject
    from app.models.course import Lesson as LessonModel
    from app.models.lesson_chunk import EMBEDDING_DIM, LessonChunk

    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:6]}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"C {uuid.uuid4().hex[:6]}",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="",
        visibility=visibility,
        status=status,
        moderation_state=moderation_state,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db.add(module)
    await db.flush()
    lesson = LessonModel(
        module_id=module.id,
        title="L",
        order=0,
        type=LessonType.text,
        data={"type": "text", "body_markdown": "alpha bravo charlie"},
    )
    db.add(lesson)
    await db.flush()
    chunk = LessonChunk(
        lesson_id=lesson.id,
        chunk_index=0,
        text="alpha bravo charlie",
        embedding=[0.1] * EMBEDDING_DIM,
        token_count=3,
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(course)
    return course, chunk


@pytest.mark.asyncio
async def test_private_non_owner_chunks_never_returned(db_session: AsyncSession):
    owner = await _owner(db_session)
    other = await _owner(db_session)
    course, chunk = await _course_with_chunk(
        db_session,
        owner,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    # `other` is not the owner -> the private course's chunk must be excluded.
    chunks = await er.find_relevant_chunks(
        db_session, course_id=course.id, query="alpha", top_k=5, viewer=other.id
    )
    assert all(c.id != chunk.id for c in chunks)
    assert chunks == []


@pytest.mark.asyncio
async def test_owner_gets_own_private_chunks(db_session: AsyncSession):
    owner = await _owner(db_session)
    course, chunk = await _course_with_chunk(
        db_session,
        owner,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    chunks = await er.find_relevant_chunks(
        db_session, course_id=course.id, query="alpha", top_k=5, viewer=owner.id
    )
    assert any(c.id == chunk.id for c in chunks)


@pytest.mark.asyncio
async def test_owner_softdeleted_draft_excluded(db_session: AsyncSession):
    """R-S12: the owner's own soft-deleted course is excluded even for them."""
    owner = await _owner(db_session)
    course, _chunk = await _course_with_chunk(
        db_session,
        owner,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
        deleted=True,
    )
    chunks = await er.find_relevant_chunks(
        db_session, course_id=course.id, query="alpha", top_k=5, viewer=owner.id
    )
    assert chunks == []


@pytest.mark.asyncio
async def test_enforce_acl_false_bypasses(db_session: AsyncSession):
    """The single bypass: enforce_acl=False returns even a non-owner's private
    chunk (used only by the owner-proven inline fallback)."""
    owner = await _owner(db_session)
    other = await _owner(db_session)
    course, chunk = await _course_with_chunk(
        db_session,
        owner,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    chunks = await er.find_relevant_chunks(
        db_session,
        course_id=course.id,
        query="alpha",
        top_k=5,
        viewer=other.id,
        enforce_acl=False,
    )
    assert any(c.id == chunk.id for c in chunks)


@pytest.mark.asyncio
async def test_listed_course_chunks_returned_to_anyone(db_session: AsyncSession):
    owner = await _owner(db_session)
    other = await _owner(db_session)
    course, chunk = await _course_with_chunk(
        db_session,
        owner,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    chunks = await er.find_relevant_chunks(
        db_session, course_id=course.id, query="alpha", top_k=5, viewer=other.id
    )
    assert any(c.id == chunk.id for c in chunks)
