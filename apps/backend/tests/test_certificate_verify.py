"""Public certificate verification by id."""

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


async def _earn_certificate(
    client: AsyncClient, teacher: dict, student: dict, subject_id: str
) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Verifiable", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
        )
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    progress = await client.post(
        f"/api/v1/me/progress/lessons/{lesson['id']}", json={"completed": True}, headers=student
    )
    cert_id = progress.json()["certificate_id"]
    return course_id, cert_id


async def test_verify_returns_public_certificate_fields(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, cert_id = await _earn_certificate(client, teacher, student, subject.id)

    r = await client.get(f"/api/v1/certificates/verify/{cert_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["certificate_id"] == cert_id
    assert body["course_id"] == course_id
    assert body["course_title"] == "Verifiable"
    assert body["learner_name"] == "Test User"
    assert "issued_at" in body
    # PII not leaked
    assert "email" not in body


async def test_verify_unknown_id_404(client: AsyncClient) -> None:
    r = await client.get("/api/v1/certificates/verify/cert_does_not_exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "cert.not_found"


async def test_verify_is_anonymous_friendly(client: AsyncClient, auth_headers, db_session) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    _, cert_id = await _earn_certificate(client, teacher, student, subject.id)

    # No auth headers passed — must work
    r = await client.get(f"/api/v1/certificates/verify/{cert_id}")
    assert r.status_code == 200
