"""Certificate PDF download."""

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


async def test_certificate_blocked_until_completion(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Cert course", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher)
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    # Not earned yet
    early = await client.get(f"/api/v1/certificates/{course_id}.pdf", headers=student)
    assert early.status_code == 403

    # Complete the only lesson
    await client.post(
        f"/api/v1/me/progress/lessons/{lesson['id']}", json={"completed": True}, headers=student
    )

    pdf = await client.get(f"/api/v1/certificates/{course_id}.pdf", headers=student)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
