"""L06, L12, L13: fresh courses get indexed, citations survive the old
label, and the synthesiser reads whole chunks."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role
from app.services import courses as courses_service
from app.services import tutor as tutor_service
from app.services import tutor_orchestrator
from app.services.tutor_subagents import retriever
from app.services.tutor_subagents.retriever import RetrieverChunk, RetrieverResult

# ---------- L12: citation ids ----------


def test_resolve_cited_lesson_id_accepts_stray_l_prefix() -> None:
    retrieved = {"abc123", "LkibKZW"}
    assert tutor_service.resolve_cited_lesson_id("abc123", retrieved) == "abc123"
    # What real models wrote when the block was labelled "Lesson L<id>".
    assert tutor_service.resolve_cited_lesson_id("Labc123", retrieved) == "abc123"
    # An id that itself starts with L still resolves to itself.
    assert tutor_service.resolve_cited_lesson_id("LkibKZW", retrieved) == "LkibKZW"
    assert tutor_service.resolve_cited_lesson_id("zzz", retrieved) is None
    assert tutor_service.resolve_cited_lesson_id("Lzzz", retrieved) is None


def test_orchestrator_keeps_prefixed_citations() -> None:
    answer = "Variance explained [L:Labc123], see also [L:abc123] and [L:ghost]."
    assert tutor_orchestrator._validate_citations(answer, {"abc123"}) == ["abc123"]


def test_synth_block_labels_chunks_with_the_citation_token() -> None:
    result = RetrieverResult(
        chunks=[RetrieverChunk(lesson_id="abc123", lesson_title="Generics", text="T is…", score=0)],
        citations=["abc123"],
    )
    block = tutor_orchestrator._serialise_for_synth("retriever", result)
    assert "[L:abc123] Generics" in block
    assert "Lesson L" not in block


# ---------- L13: whole chunks reach the synthesiser ----------


def test_synthesiser_reads_a_full_chunk() -> None:
    # One chunk is ~500 tokens (about 2,000 characters); 600 cut most of it.
    assert retriever.EXCERPT_CHARS >= 2000
    assert tutor_service.CONTEXT_EXCERPT_CHARS >= 2000


# ---------- L06: indexing outside publish ----------


async def _course_with_module(client: AsyncClient, headers: dict, db: AsyncSession) -> tuple:
    subject = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(subject)
    await db.commit()
    course = await client.post(
        "/api/v1/courses",
        json={"title": "Draft course", "subject_id": subject.id, "overview": "x"},
        headers=headers,
    )
    course_id = course.json()["id"]
    module = await client.post(
        f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=headers
    )
    return course_id, module.json()["id"]


async def test_lesson_writes_reindex_the_draft_course(
    client: AsyncClient, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(courses_service, "_schedule_embedding_index", scheduled.append)
    headers = await auth_headers(role=Role.instructor)
    course_id, module_id = await _course_with_module(client, headers, db_session)

    created = await client.post(
        f"/api/v1/courses/modules/{module_id}/lessons",
        json={"title": "One", "type": "text", "data": {"type": "text", "body_markdown": "a"}},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    lesson_id = created.json()["id"]
    updated = await client.patch(
        f"/api/v1/courses/lessons/{lesson_id}",
        json={"data": {"type": "text", "body_markdown": "b"}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    deleted = await client.delete(f"/api/v1/courses/lessons/{lesson_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text

    assert scheduled == [course_id, course_id, course_id]
