"""Regression: archiving a course must not lock out already-enrolled learners.

Before iteration 24, ``GET /api/v1/courses/{slug}`` filtered visibility
through ``can_view_unpublished``, which only let owners and admins read
non-published courses. So when an instructor archived a course (or moved
it back to draft), every existing enrolled learner started getting a 404
and lost access to the syllabus, the chat link, and their certificate
download CTA.

The ``can_view_course`` helper (now the central S2 authorizer, ADR-0026 §3)
keeps that rule: a publicly-listed course + owners + admins + ENROLLED learners
(grandfathered, R-VIS-13) can all read the detail page even after it leaves the
public catalog.

S2 / ADR-0026 contract notes:
* Publishing keeps a course PRIVATE; a learner can only enroll while the course
  is publicly LISTED (public + approved + published), so the enrolled-course
  helper uses ``publish_and_list_course``.
* ``PATCH {status}`` is gone (FR-VIS-08). Unpublish (published→draft) is the
  ``POST /unpublish`` lifecycle endpoint. ``archived`` has no owner-facing HTTP
  transition in S2, so the archive step is driven against the service-layer
  state machine (``_transition_status``), which also force-privates the course
  exactly as a real archive would (ADR-0026 §4).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import CourseStatus, Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _archive_course(db: AsyncSession, course_id: str) -> None:
    """Archive a course via the service-layer state machine.

    There is no owner-facing ``/archive`` HTTP endpoint in S2 (owner lifecycle is
    publish/unpublish only); ``_transition_status`` to ``archived`` runs the same
    published→archived transition + force-private side-effects a real archive
    would, which is what these access-after-archive assertions care about.
    """
    from app.repositories import courses as courses_repo
    from app.services import courses as courses_service

    course = await courses_repo.get_course(db, course_id)
    await courses_service._transition_status(db, course, CourseStatus.archived)
    await db.commit()


async def _enrolled_course(
    client: AsyncClient,
    teacher: dict,
    student: dict,
    subject_id: str,
    seed_lesson,
    publish_and_list_course,
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Archived", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await publish_and_list_course(course_id, teacher)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    return course_id


async def test_enrolled_learner_still_sees_archived_course(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled_course(
        client, teacher, student, subject.id, seed_lesson, publish_and_list_course
    )

    # While published, both can read the detail
    pub = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert pub.status_code == 200

    # Instructor archives the course (service-layer transition; no HTTP route).
    await _archive_course(db_session, course_id)

    # The enrolled learner still has access to the syllabus
    after = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert after.status_code == 200, after.text
    assert after.json()["status"] == "archived"
    assert after.json()["is_enrolled"] is True


async def test_archived_course_is_invisible_to_non_enrolled_strangers(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    enrolled = await auth_headers(role=Role.student)
    stranger = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled_course(
        client, teacher, enrolled, subject.id, seed_lesson, publish_and_list_course
    )

    await _archive_course(db_session, course_id)

    # clear accumulated login cookies so the "anonymous"
    # request below isn't auto-authed as the most recent user.
    client.cookies.clear()

    # Anonymous: still 404
    anon = await client.get(f"/api/v1/courses/{course_id}")
    assert anon.status_code == 404

    # A logged-in but not-enrolled user: still 404
    other = await client.get(f"/api/v1/courses/{course_id}", headers=stranger)
    assert other.status_code == 404


async def test_unpublished_back_to_draft_keeps_enrolled_access(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled_course(
        client, teacher, student, subject.id, seed_lesson, publish_and_list_course
    )

    # Unpublish (back to draft) via the lifecycle endpoint (PATCH {status} is
    # gone — FR-VIS-08). This also force-privates the course (ADR-0026 §4).
    unpub = await client.post(f"/api/v1/courses/{course_id}/unpublish", headers=teacher)
    assert unpub.status_code == 200

    after = await client.get(f"/api/v1/courses/{course_id}", headers=student)
    assert after.status_code == 200
    assert after.json()["status"] == "draft"
