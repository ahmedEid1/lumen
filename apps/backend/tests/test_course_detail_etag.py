"""ETag + If-None-Match on course detail.

The course detail endpoint is the highest-traffic personalised-but-
cacheable read in the API (every catalog click, every learner
returning to /learn). Pre-iter 76 every hit re-served the same body
even when nothing had changed. The new ETag is a weak hash of
``(course_id, updated_at, viewer-derived flags, stats counters)`` —
covers everything that goes into the response, so a server-side
change (publish, new enrollment, rating shift) invalidates it
automatically. A returning client gets ``304 Not Modified`` (no
body) instead of N kB of JSON.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _published(
    client: AsyncClient, teacher: dict, subject_id: str, seed_lesson
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "ETag", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    return course_id


async def test_first_request_returns_etag(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)

    r = await client.get(f"/api/v1/courses/{course_id}")
    assert r.status_code == 200
    etag = r.headers.get("etag")
    assert etag is not None
    # Weak ETag — RFC 7232 §2.3, must begin with W/
    assert etag.startswith('W/"')


async def test_matching_if_none_match_returns_304_no_body(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)

    first = await client.get(f"/api/v1/courses/{course_id}")
    etag = first.headers["etag"]

    second = await client.get(
        f"/api/v1/courses/{course_id}", headers={"If-None-Match": etag}
    )
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers.get("etag") == etag


async def test_etag_changes_when_course_changes(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)

    first = await client.get(f"/api/v1/courses/{course_id}")
    first_etag = first.headers["etag"]

    # Rename the course → updated_at changes → ETag changes.
    rename = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"title": "ETag Renamed"},
        headers=teacher,
    )
    assert rename.status_code == 200

    second = await client.get(f"/api/v1/courses/{course_id}")
    assert second.status_code == 200
    assert second.headers["etag"] != first_etag


async def test_etag_differs_for_enrolled_vs_anonymous(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Per-viewer fields (is_enrolled, progress_pct) are in the body, so
    the ETag must differ — otherwise a cached anonymous response could
    be served to an enrolled learner missing their personal data."""
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)

    anon = await client.get(f"/api/v1/courses/{course_id}")
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    authed = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert anon.headers["etag"] != authed.headers["etag"]


async def test_mismatched_if_none_match_returns_full_body(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)

    r = await client.get(
        f"/api/v1/courses/{course_id}",
        headers={"If-None-Match": 'W/"stale-etag"'},
    )
    assert r.status_code == 200
    assert r.json()["id"] == course_id
