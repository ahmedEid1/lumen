"""Per-course analytics."""

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


async def _full_course(
    client: AsyncClient, headers: dict, subject_id: str, *, title: str = "C"
) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=headers)
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=headers,
        )
    ).json()
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=headers)
    return course_id, lesson["id"]


async def test_analytics_requires_owner_or_admin(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher_a = await auth_headers(role=Role.instructor)
    teacher_b = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, _ = await _full_course(client, teacher_a, subject.id)

    r = await client.get(f"/api/v1/courses/{course_id}/analytics", headers=teacher_b)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "analytics.forbidden"


async def test_analytics_reflects_enrollment_and_completion(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_a = await auth_headers(role=Role.student)
    student_b = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _full_course(client, teacher, subject.id)

    # zero state
    base = await client.get(f"/api/v1/courses/{course_id}/analytics", headers=teacher)
    assert base.status_code == 200
    assert base.json()["enrollments"] == 0
    assert base.json()["completion_rate"] == 0.0
    assert base.json()["avg_rating"] is None

    # one enrollment with completion + review
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_a)
    await client.post(
        f"/api/v1/me/progress/lessons/{lesson_id}", json={"completed": True}, headers=student_a
    )
    await client.put(
        f"/api/v1/courses/{course_id}/reviews", json={"rating": 5, "body": "great"}, headers=student_a
    )
    # one enrollment with no completion
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_b)

    r = await client.get(f"/api/v1/courses/{course_id}/analytics", headers=teacher)
    body = r.json()
    assert body["enrollments"] == 2
    assert body["completions"] == 1
    assert body["completion_rate"] == 0.5
    assert body["avg_rating"] == 5.0
    assert body["rating_count"] == 1
    # avg progress = (100 + 0) / 2 = 50.0
    assert body["avg_progress_pct"] == 50.0
    assert body["enrollments_last_7d"] == 2
