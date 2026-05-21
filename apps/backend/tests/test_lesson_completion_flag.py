"""CourseDetail surfaces per-lesson ``completed`` for the enrolled viewer."""

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


async def _two_lesson_course(client: AsyncClient, teacher: dict, subject_id: str) -> tuple[str, str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Two", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher)
    ).json()
    a = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "A", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()
    b = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "B", "type": "text", "data": {"type": "text", "body_markdown": "y"}},
            headers=teacher,
        )
    ).json()
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)
    return course_id, a["id"], b["id"]


def _lesson(detail: dict, lesson_id: str) -> dict:
    for module in detail["modules"]:
        for lesson in module["lessons"]:
            if lesson["id"] == lesson_id:
                return lesson
    raise AssertionError(f"lesson {lesson_id} missing from detail")


async def test_completed_flag_reflects_per_viewer_progress(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, a, b = await _two_lesson_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    before = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert before.status_code == 200
    assert _lesson(before.json(), a)["completed"] is False
    assert _lesson(before.json(), b)["completed"] is False

    await client.post(
        f"/api/v1/me/progress/lessons/{a}", json={"completed": True}, headers=student
    )

    after = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert _lesson(after.json(), a)["completed"] is True
    assert _lesson(after.json(), b)["completed"] is False


async def test_completed_flag_is_per_viewer(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_a = await auth_headers(role=Role.student)
    student_b = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, a, b = await _two_lesson_course(client, teacher, subject.id)

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_a)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_b)
    await client.post(
        f"/api/v1/me/progress/lessons/{a}", json={"completed": True}, headers=student_a
    )

    a_view = await client.get(f"/api/v1/courses/{course_id}", headers=student_a)
    b_view = await client.get(f"/api/v1/courses/{course_id}", headers=student_b)
    assert _lesson(a_view.json(), a)["completed"] is True
    assert _lesson(b_view.json(), a)["completed"] is False


async def test_completed_flag_false_for_anon_and_non_enrolled(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, a, _ = await _two_lesson_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    await client.post(
        f"/api/v1/me/progress/lessons/{a}", json={"completed": True}, headers=student
    )

    # Iter 115: clear cookies so the "anonymous" GET below isn't
    # promoted to the student's session by the cookie jar.
    client.cookies.clear()
    # Anonymous detail: all completion flags default False
    anon = await client.get(f"/api/v1/courses/{course_id}")
    assert anon.status_code == 200
    assert _lesson(anon.json(), a)["completed"] is False

    # Different signed-in user with no enrollment: also False
    stranger = await auth_headers(role=Role.student)
    other = await client.get(f"/api/v1/courses/{course_id}", headers=stranger)
    assert _lesson(other.json(), a)["completed"] is False
