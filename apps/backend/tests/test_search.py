"""Search endpoint with the Postgres fallback backend."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import Subject
from app.models.user import Role


@pytest.fixture(autouse=True)
def _force_pg_backend(monkeypatch):
    monkeypatch.setenv("SEARCH_BACKEND", "postgres")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _publish(
    client: AsyncClient, headers: dict, subject_id: str, title: str, overview: str, seed_lesson
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": overview},
        headers=headers,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, headers)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=headers
    )
    return course_id


async def test_search_finds_by_title(
    client: AsyncClient, auth_headers, db_session, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    await _publish(
        client, teacher, subject.id, "Async Python deep dive", "Coroutines.", seed_lesson
    )
    await _publish(client, teacher, subject.id, "JavaScript essentials", "Closures.", seed_lesson)

    r = await client.get("/api/v1/search/courses?q=Python")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    titles = [c["title"] for c in body["items"]]
    assert any("Python" in t for t in titles)
    assert all("JavaScript" not in t for t in titles)


async def test_search_filters_difficulty(
    client: AsyncClient, auth_headers, db_session, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    await _publish(client, teacher, subject.id, "Easy course", "intro stuff", seed_lesson)
    # No way to set difficulty on create yet via patch; default is beginner.

    r = await client.get("/api/v1/search/courses?q=Easy&difficulty=beginner")
    assert r.status_code == 200
    assert any("Easy" in c["title"] for c in r.json()["items"])


async def test_search_requires_q(client: AsyncClient) -> None:
    r = await client.get("/api/v1/search/courses")
    assert r.status_code == 422


async def test_search_returns_empty_for_no_match(client: AsyncClient) -> None:
    r = await client.get("/api/v1/search/courses?q=zzzzzzz_no_match")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []
