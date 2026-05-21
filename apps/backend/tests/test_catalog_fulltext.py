"""Postgres full-text ranking on the catalog search.

Earlier the catalog `?q=...` was pure ILIKE substring match —
no relevance ordering, no quoted-phrase support, partial-word
matches only by coincidence. The Postgres ``websearch_to_tsquery``
+ ``ts_rank`` upgrade adds:

* word-stem matching ("running" → "run"),
* relevance ordering (title hits rank above body hits via
  ts_rank's term-position weighting),
* a substring ILIKE fallback so "java" still finds "javascript"
  (the FTS would only find "java" or "javas").

We pin the *behavioural* contract here — title hits rank above
body-only hits when the default sort applies; an explicit sort
override still wins (rank becomes the tiebreaker).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


@pytest.fixture(autouse=True)
def _force_pg_search(monkeypatch):
    """The repository function is shared by the catalog and the
    Postgres-fallback search backend. Make sure we're exercising the
    PG path and not Meili."""
    from app.core.config import get_settings

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
    teacher: dict,
    subject_id: str,
    title: str,
    overview: str,
    seed_lesson,
) -> str:
    r = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": overview},
        headers=teacher,
    )
    course_id = r.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    return course_id


async def test_title_hit_ranks_above_body_hit(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    # Two courses — the one with "Python" in the title should rank
    # above the one that only mentions Python in the overview.
    body_hit = await _publish(
        client, teacher, subject.id,
        "Web fundamentals",
        "An intro covering HTML, CSS, JavaScript and a touch of Python.",
        seed_lesson,
    )
    title_hit = await _publish(
        client, teacher, subject.id,
        "Python for beginners",
        "Variables, loops, functions.",
        seed_lesson,
    )

    r = await client.get("/api/v1/courses?q=python")
    assert r.status_code == 200
    items = r.json()["items"]
    titles = [(i["id"], i["title"]) for i in items]
    title_hit_pos = next(i for i, (cid, _) in enumerate(titles) if cid == title_hit)
    body_hit_pos = next(i for i, (cid, _) in enumerate(titles) if cid == body_hit)
    assert title_hit_pos < body_hit_pos, titles


async def test_partial_word_still_matches_via_ilike_fallback(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """FTS would tokenise "javascript" and not match "java" as a
    prefix. The ILIKE fallback keeps the discovery UX intuitive."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    await _publish(
        client, teacher, subject.id,
        "JavaScript essentials",
        "Closures, promises, the event loop.",
        seed_lesson,
    )

    r = await client.get("/api/v1/courses?q=java")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert ids, "ILIKE fallback should have surfaced JavaScript on a 'java' query"


async def test_word_stem_matches_via_fts(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Postgres english config stems — 'running' matches 'run' and
    vice versa. That's the user-visible win over the ILIKE-only path."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    await _publish(
        client, teacher, subject.id,
        "Running benchmarks",
        "Measuring throughput properly.",
        seed_lesson,
    )

    r = await client.get("/api/v1/courses?q=run")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert ids


async def test_no_query_still_paginates_by_sort(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Sanity: when q is omitted, the rank column isn't added to
    ORDER BY and the user's chosen sort is the only ordering."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    for title in ("Alpha", "Bravo", "Charlie"):
        await _publish(client, teacher, subject.id, title, "x", seed_lesson)
    r = await client.get("/api/v1/courses?sort=title")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert titles == sorted(titles)
