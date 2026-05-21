"""Regression: dashboard must hide enrollments to soft-deleted courses.

Before iteration 26 ``list_enrollments_for_user`` did not filter on
``Course.deleted_at``, so a learner whose course got soft-deleted by the
instructor (or by admin cleanup) saw a phantom "in progress" card whose
Continue link 404'd against ``GET /api/v1/courses/{slug}``.

Archived / draft courses are different — those still surface to keep
enrolled learners' content available (see iteration 24). Only truly
deleted courses disappear.
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


async def _enrolled(
    client: AsyncClient, teacher: dict, student: dict, subject_id: str, title: str, seed_lesson
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    return course_id


async def test_soft_deleted_courses_drop_off_the_dashboard(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)

    keep_id = await _enrolled(client, teacher, student, subject.id, "Keeps", seed_lesson)
    drop_id = await _enrolled(client, teacher, student, subject.id, "Drops", seed_lesson)

    before = await client.get("/api/v1/me/enrollments", headers=student)
    ids_before = {e["course"]["id"] for e in before.json()}
    assert {keep_id, drop_id}.issubset(ids_before)

    # Instructor soft-deletes one of the courses
    deleted = await client.delete(f"/api/v1/courses/{drop_id}", headers=teacher)
    assert deleted.status_code == 200

    after = await client.get("/api/v1/me/enrollments", headers=student)
    ids_after = {e["course"]["id"] for e in after.json()}
    assert keep_id in ids_after
    assert drop_id not in ids_after, "Soft-deleted course must not appear on the dashboard"


async def test_archived_courses_still_appear_on_dashboard(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Companion to iteration 24: archive ≠ delete; learners keep access."""
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _enrolled(client, teacher, student, subject.id, "Archived", seed_lesson)

    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=teacher
    )

    listing = await client.get("/api/v1/me/enrollments", headers=student)
    ids = {e["course"]["id"] for e in listing.json()}
    assert course_id in ids
