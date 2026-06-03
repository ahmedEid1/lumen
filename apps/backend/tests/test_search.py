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
    client: AsyncClient,
    headers: dict,
    subject_id: str,
    title: str,
    overview: str,
    seed_lesson,
    db: AsyncSession,
) -> str:
    """Create + seed + publish AND publicly list (S2 / ADR-0026).

    ``PATCH {status: "published"}`` is now a 422 (lifecycle moved to
    ``POST /courses/{id}/publish``), and publishing keeps a course private.
    Search/catalog only surface ``is_publicly_listed`` courses, so drive all
    three axes to the publicly-listed state via the DB session — mirroring
    S2's own ``_mk_course`` helper.
    """
    from sqlalchemy import update

    from app.models.course import Course, CourseStatus, ModerationState, Visibility

    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": overview},
        headers=headers,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, headers)
    await db.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(
            status=CourseStatus.published,
            visibility=Visibility.public,
            moderation_state=ModerationState.approved,
        )
    )
    await db.commit()
    return course_id


async def test_search_finds_by_title(
    client: AsyncClient, auth_headers, db_session, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    await _publish(
        client,
        teacher,
        subject.id,
        "Async Python deep dive",
        "Coroutines.",
        seed_lesson,
        db_session,
    )
    await _publish(
        client, teacher, subject.id, "JavaScript essentials", "Closures.", seed_lesson, db_session
    )

    r = await client.get("/api/v1/courses?q=Python")
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
    await _publish(
        client, teacher, subject.id, "Easy course", "intro stuff", seed_lesson, db_session
    )
    # No way to set difficulty on create yet via patch; default is beginner.

    r = await client.get("/api/v1/courses?q=Easy&difficulty=beginner")
    assert r.status_code == 200
    assert any("Easy" in c["title"] for c in r.json()["items"])


async def test_search_without_q_returns_browse_listing(client: AsyncClient) -> None:
    # /api/v1/courses lists the catalog when `q` is absent — there's no
    # longer a search-only alias that 422s on missing q. Iter 2 (QA loop)
    # collapsed /api/v1/search/courses into the catalog because both
    # called the same `search_courses` repo function; the FE never used
    # the dedicated alias and keeping it forced a tests/docs gap.
    r = await client.get("/api/v1/courses")
    assert r.status_code == 200
    assert "items" in r.json()


async def test_search_returns_empty_for_no_match(client: AsyncClient) -> None:
    r = await client.get("/api/v1/courses?q=zzzzzzz_no_match")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []
