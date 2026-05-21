"""Course bookmarks."""

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


async def _publish(client: AsyncClient, headers: dict, subject_id: str, seed_lesson) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Bookmarkable", "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, headers)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=headers)
    return course_id


async def test_bookmark_round_trip(client: AsyncClient, auth_headers, db_session, seed_lesson) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _publish(client, teacher, subject.id, seed_lesson)

    # empty bookmarks
    empty = await client.get("/api/v1/me/bookmarks", headers=student)
    assert empty.status_code == 200
    assert empty.json() == []

    # add
    add = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    assert add.status_code == 201

    # idempotent re-add
    again = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    assert again.status_code == 201

    # listed
    listed = await client.get("/api/v1/me/bookmarks", headers=student)
    assert listed.status_code == 200
    assert any(c["id"] == course_id for c in listed.json())

    # course detail surfaces is_bookmarked=true for the bookmarker
    detail = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert detail.status_code == 200
    assert detail.json()["is_bookmarked"] is True

    # remove
    rem = await client.delete(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    assert rem.status_code == 200

    after = await client.get("/api/v1/me/bookmarks", headers=student)
    assert after.json() == []


async def test_bookmark_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/me/bookmarks")
    assert r.status_code == 401


async def test_bookmark_unknown_course_404(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.put("/api/v1/me/bookmarks/does-not-exist", headers=h)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "course.not_found"
