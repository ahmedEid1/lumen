"""Notifications API + auto-creation on enroll."""

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


async def test_enroll_creates_welcome_notification_and_can_mark_read(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Notify course", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    notes = await client.get("/api/v1/me/notifications", headers=student)
    assert notes.status_code == 200
    items = notes.json()
    assert any(n["kind"] == "enrolled" and not n["read_at"] for n in items)

    nid = next(n["id"] for n in items if n["kind"] == "enrolled")
    read = await client.post(f"/api/v1/me/notifications/{nid}/read", headers=student)
    assert read.status_code == 200

    again = await client.get("/api/v1/me/notifications", headers=student)
    assert all(n["read_at"] is not None for n in again.json() if n["id"] == nid)
