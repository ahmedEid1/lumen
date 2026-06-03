"""Regression: a course cannot be published with zero live lessons.

Before iteration 43, ``_transition_status`` checked only ``title`` and
``overview`` when transitioning to ``published``. So an instructor
could create a course, fill in those two fields, and click publish to
push an empty shell into the catalog. Students who enrolled landed on
a blank syllabus, progress stuck at 0%, with no signal that the
author hadn't finished.

The same rule applies after the fact: soft-deleting the last lesson
and then publishing again from draft must fail.

S2 / ADR-0026 (FR-VIS-08) moved the publish action off ``PATCH {status}``
(now a 422 — ``CourseUpdate`` is ``extra=forbid``) onto the lifecycle
endpoint ``POST /courses/{id}/publish``. The no-lessons guard lives in
``_transition_status`` and still fires on that path; these tests pin that
the guard survived the lifecycle move, returning ``course.no_lessons``.
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


async def test_publish_rejected_when_no_lessons(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Empty", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]

    r = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers=teacher,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "course.no_lessons"

    # Sanity: the course is still draft and not in the catalog.
    detail = await client.get(f"/api/v1/courses/{course_id}", headers=teacher)
    assert detail.json()["status"] == "draft"
    catalog = await client.get("/api/v1/courses?page=1&page_size=50")
    assert all(c["id"] != course_id for c in catalog.json()["items"])


async def test_publish_rejected_with_modules_but_no_lessons(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Outline only", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    # Add a module — but no lessons inside it.
    m = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": "Intro"},
        headers=teacher,
    )
    assert m.status_code == 201

    r = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers=teacher,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "course.no_lessons"


async def test_publish_succeeds_with_a_lesson(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Real", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)

    r = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"


async def test_republish_blocked_if_all_lessons_soft_deleted(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Round trip", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    lesson_id = await seed_lesson(course_id, teacher)
    pub = await client.post(f"/api/v1/courses/{course_id}/publish", headers=teacher)
    assert pub.status_code == 200

    # Move back to draft (lifecycle /unpublish), then soft-delete the only lesson.
    unpub = await client.post(f"/api/v1/courses/{course_id}/unpublish", headers=teacher)
    assert unpub.status_code == 200
    drop = await client.delete(f"/api/v1/courses/lessons/{lesson_id}", headers=teacher)
    assert drop.status_code == 200

    # Now publishing again must be rejected.
    r = await client.post(f"/api/v1/courses/{course_id}/publish", headers=teacher)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "course.no_lessons"
