"""Chat REST: history + post + permissions."""

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


async def _published_course(client: AsyncClient, headers: dict, subject_id: str, seed_lesson) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Chat course", "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, headers)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=headers)
    return course_id


async def test_chat_post_requires_enrollment(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published_course(client, teacher, subject.id, seed_lesson)

    bad = await client.post(
        f"/api/v1/chat/courses/{course_id}/messages",
        json={"body": "hi"},
        headers=student,
    )
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "chat.enroll_first"

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    ok = await client.post(
        f"/api/v1/chat/courses/{course_id}/messages",
        json={"body": "hi"},
        headers=student,
    )
    assert ok.status_code == 201
    assert ok.json()["body"] == "hi"


async def test_chat_owner_can_post_without_enroll(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _published_course(client, teacher, subject.id, seed_lesson)

    r = await client.post(
        f"/api/v1/chat/courses/{course_id}/messages",
        json={"body": "owner message"},
        headers=teacher,
    )
    assert r.status_code == 201

    history = await client.get(f"/api/v1/chat/courses/{course_id}/messages", headers=teacher)
    assert history.status_code == 200
    assert any(m["body"] == "owner message" for m in history.json()["items"])
