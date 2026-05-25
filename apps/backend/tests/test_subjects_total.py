"""Regression: subject.total_courses must exclude soft-deleted courses.

Before iteration 30 ``list_subjects`` outer-joined Course with
``status == published`` only — a soft-deleted course retains its
``status`` until reaped, so it kept inflating the badge on the catalog
subject tile.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Subj", slug=f"subj-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _publish(
    client: AsyncClient, teacher: dict, subject_id: str, title: str, seed_lesson
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    cid = create.json()["id"]
    await seed_lesson(cid, teacher)
    await client.patch(f"/api/v1/courses/{cid}", json={"status": "published"}, headers=teacher)
    return cid


async def _total_for(client: AsyncClient, subject_id: str) -> int:
    subjects = await client.get("/api/v1/subjects")
    assert subjects.status_code == 200
    row = next(s for s in subjects.json() if s["id"] == subject_id)
    return int(row["total_courses"] or 0)


async def test_total_drops_when_a_published_course_is_soft_deleted(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)

    a = await _publish(client, teacher, subject.id, "A", seed_lesson)
    b = await _publish(client, teacher, subject.id, "B", seed_lesson)
    assert await _total_for(client, subject.id) == 2

    deleted = await client.delete(f"/api/v1/courses/{a}", headers=teacher)
    assert deleted.status_code == 200

    assert await _total_for(client, subject.id) == 1
    # Sanity: the surviving course is still in the catalog
    catalog = await client.get(f"/api/v1/courses?subject={subject.slug}")
    assert any(c["id"] == b for c in catalog.json()["items"])
    assert all(c["id"] != a for c in catalog.json()["items"])


async def test_draft_and_archived_dont_count_either(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)

    # Draft course never published — shouldn't count
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Draft", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    assert create.status_code == 201

    # Archived course (transitioned via published → archived) shouldn't count
    archived = await _publish(client, teacher, subject.id, "Was published", seed_lesson)
    await client.patch(f"/api/v1/courses/{archived}", json={"status": "archived"}, headers=teacher)

    assert await _total_for(client, subject.id) == 0
