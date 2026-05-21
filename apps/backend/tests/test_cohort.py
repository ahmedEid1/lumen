"""Per-course cohort listing for instructors."""

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


async def _full_course(client: AsyncClient, headers: dict, subject_id: str) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Cohort", "subject_id": subject_id, "overview": "x"},
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


async def test_cohort_requires_owner_or_admin(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher_a = await auth_headers(role=Role.instructor)
    teacher_b = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, _ = await _full_course(client, teacher_a, subject.id)

    r = await client.get(f"/api/v1/courses/{course_id}/students", headers=teacher_b)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cohort.forbidden"


async def test_cohort_lists_students_with_progress(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_a = await auth_headers(role=Role.student)
    student_b = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _full_course(client, teacher, subject.id)

    # student_a finishes, student_b enrols but does nothing
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_a)
    await client.post(
        f"/api/v1/me/progress/lessons/{lesson_id}", json={"completed": True}, headers=student_a
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_b)

    r = await client.get(f"/api/v1/courses/{course_id}/students", headers=teacher)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    by_pct = {row["progress_pct"] for row in rows}
    assert 100.0 in by_pct
    assert 0.0 in by_pct
    finished = [row for row in rows if row["progress_pct"] == 100.0][0]
    assert finished["completed_at"] is not None
    assert finished["certificate_id"] is not None


async def test_cohort_unknown_course_404(client: AsyncClient, auth_headers) -> None:
    teacher = await auth_headers(role=Role.instructor)
    r = await client.get("/api/v1/courses/does-not-exist/students", headers=teacher)
    assert r.status_code == 404
