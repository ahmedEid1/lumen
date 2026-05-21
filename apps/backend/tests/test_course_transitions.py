"""Course status transitions, ownership, soft-delete visibility."""

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


async def test_invalid_transition_blocked(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "X", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = r.json()["id"]
    await seed_lesson(course_id, teacher)
    # draft → published → archived is allowed
    pub = await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    assert pub.status_code == 200
    arch = await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=teacher
    )
    assert arch.status_code == 200
    # archived → published is NOT allowed
    bad = await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "course.invalid_transition"


async def test_only_owner_or_admin_can_edit(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher_a = await auth_headers(role=Role.instructor)
    teacher_b = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Owned", "subject_id": subject.id, "overview": "x"},
        headers=teacher_a,
    )
    course_id = r.json()["id"]
    bad = await client.patch(
        f"/api/v1/courses/{course_id}", json={"title": "Hijacked"}, headers=teacher_b
    )
    assert bad.status_code == 403


async def test_admin_can_edit_any_course(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Owned", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = r.json()["id"]
    edit = await client.patch(
        f"/api/v1/courses/{course_id}", json={"title": "Renamed by admin"}, headers=admin
    )
    assert edit.status_code == 200
    assert edit.json()["title"] == "Renamed by admin"


async def test_soft_delete_hides_from_catalog(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Soon gone", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = r.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)

    catalog = await client.get("/api/v1/courses?page=1&page_size=50")
    assert any(c["id"] == course_id for c in catalog.json()["items"])

    deleted = await client.delete(f"/api/v1/courses/{course_id}", headers=teacher)
    assert deleted.status_code == 200

    catalog2 = await client.get("/api/v1/courses?page=1&page_size=50")
    assert all(c["id"] != course_id for c in catalog2.json()["items"])
