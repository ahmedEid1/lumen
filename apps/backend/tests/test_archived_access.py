"""Regression: archiving a course must not lock out already-enrolled learners.

Before iteration 24, ``GET /api/v1/courses/{slug}`` filtered visibility
through ``can_view_unpublished``, which only let owners and admins read
non-published courses. So when an instructor archived a course (or moved
it back to draft), every existing enrolled learner started getting a 404
and lost access to the syllabus, the chat link, and their certificate
download CTA.

The new ``can_view_course`` helper extends the rule with an enrolment
lookup — published courses + owners + admins + enrolled learners can all
read the detail page.
"""

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


async def _enrolled_course(
    client: AsyncClient, teacher: dict, student: dict, subject_id: str, seed_lesson
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Archived", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    return course_id


async def test_enrolled_learner_still_sees_archived_course(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled_course(client, teacher, student, subject.id, seed_lesson)

    # While published, both can read the detail
    pub = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert pub.status_code == 200

    # Instructor archives the course
    arch = await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=teacher
    )
    assert arch.status_code == 200

    # The enrolled learner still has access to the syllabus
    after = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert after.status_code == 200, after.text
    assert after.json()["status"] == "archived"
    assert after.json()["is_enrolled"] is True


async def test_archived_course_is_invisible_to_non_enrolled_strangers(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    enrolled = await auth_headers(role=Role.student)
    stranger = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled_course(client, teacher, enrolled, subject.id, seed_lesson)

    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=teacher
    )

    # Iter 115: clear accumulated login cookies so the "anonymous"
    # request below isn't auto-authed as the most recent user.
    client.cookies.clear()

    # Anonymous: still 404
    anon = await client.get(f"/api/v1/courses/{course_id}")
    assert anon.status_code == 404

    # A logged-in but not-enrolled user: still 404
    other = await client.get(f"/api/v1/courses/{course_id}", headers=stranger)
    assert other.status_code == 404


async def test_unpublished_back_to_draft_keeps_enrolled_access(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled_course(client, teacher, student, subject.id, seed_lesson)

    # Unpublish (back to draft)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "draft"}, headers=teacher)

    after = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert after.status_code == 200
    assert after.json()["status"] == "draft"
