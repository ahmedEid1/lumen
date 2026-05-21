"""GET /courses/{id}/students.csv — instructor cohort export.

Reuses the cohort_for_course service so authz / soft-delete handling
/ the 500-row cap all apply identically to the CSV path. We just
verify the wire format here and that the auth gate works.
"""

from __future__ import annotations

import csv
import io
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


async def _published_with_lesson(
    client: AsyncClient, teacher: dict, subject_id: str, seed_lesson
) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "CSV", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    lesson_id = await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    return course_id, lesson_id


async def test_csv_emits_header_row_and_one_row_per_student(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_a = await auth_headers(role=Role.student)
    student_b = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _published_with_lesson(client, teacher, subject.id, seed_lesson)

    # student_a completes; student_b enrols only
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_a)
    await client.post(
        f"/api/v1/me/progress/lessons/{lesson_id}",
        json={"completed": True},
        headers=student_a,
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_b)

    r = await client.get(
        f"/api/v1/courses/{course_id}/students.csv", headers=teacher
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    # Don't cache the cohort dump on shared infrastructure.
    assert "no-store" in r.headers["cache-control"]

    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    assert reader.fieldnames == [
        "user_id",
        "full_name",
        "enrolled_at",
        "completed_at",
        "progress_pct",
        "certificate_id",
    ]
    assert len(rows) == 2
    # One row must be the completer with a certificate_id.
    finished = [row for row in rows if row["progress_pct"] == "100.0"]
    assert len(finished) == 1
    assert finished[0]["certificate_id"]  # non-empty
    assert finished[0]["completed_at"]  # ISO timestamp
    # The other is in progress.
    pending = [row for row in rows if row["progress_pct"] == "0.0"]
    assert len(pending) == 1
    assert pending[0]["completed_at"] == ""
    assert pending[0]["certificate_id"] == ""


async def test_csv_requires_owner_or_admin(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    other_teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, _ = await _published_with_lesson(client, teacher, subject.id, seed_lesson)

    r = await client.get(
        f"/api/v1/courses/{course_id}/students.csv", headers=other_teacher
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cohort.forbidden"


async def test_csv_handles_special_chars_in_names(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user, seed_lesson
) -> None:
    """Names with commas / quotes / newlines must be CSV-quoted properly."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, _ = await _published_with_lesson(client, teacher, subject.id, seed_lesson)

    weird = await make_user(
        email=f"weird-{uuid.uuid4().hex[:6]}@lumen.test",
        full_name='Smith, "Quoted" \n Newline',
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": weird.email, "password": "Password!1234"},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=h)

    r = await client.get(
        f"/api/v1/courses/{course_id}/students.csv", headers=teacher
    )
    assert r.status_code == 200
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    weird_row = next(row for row in rows if row["user_id"] == weird.id)
    assert weird_row["full_name"] == 'Smith, "Quoted" \n Newline'
