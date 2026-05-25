"""Regression: progress % must not exceed 100% after a lesson is soft-deleted.

Before iteration 22, `count_completed_lessons` counted every
``LessonProgress`` row for an enrollment regardless of whether the lesson
still existed. Soft-deleting a lesson the learner had already finished
left ``done`` larger than ``total``, which surfaced as >100% progress and
could mint spurious certificates.
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


async def _publish_with_two_lessons(
    client: AsyncClient, headers: dict, subject_id: str
) -> tuple[str, str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Shrinker", "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=headers
        )
    ).json()
    l1 = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "A", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=headers,
        )
    ).json()
    l2 = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "B", "type": "text", "data": {"type": "text", "body_markdown": "y"}},
            headers=headers,
        )
    ).json()
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=headers
    )
    return course_id, l1["id"], l2["id"]


async def test_progress_does_not_exceed_100_after_lesson_soft_delete(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, l1, l2 = await _publish_with_two_lessons(client, teacher, subject.id)

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    # Complete both lessons
    await client.post(
        f"/api/v1/me/progress/lessons/{l1}", json={"completed": True}, headers=student
    )
    final = await client.post(
        f"/api/v1/me/progress/lessons/{l2}", json={"completed": True}, headers=student
    )
    assert final.json()["progress_pct"] == 100.0

    # Instructor soft-deletes lesson A after the student finished it.
    deleted = await client.delete(f"/api/v1/courses/lessons/{l1}", headers=teacher)
    assert deleted.status_code == 200

    # Re-mark lesson B (touches the progress calculation) — pct must clamp to 100
    after = await client.post(
        f"/api/v1/me/progress/lessons/{l2}", json={"completed": True}, headers=student
    )
    body = after.json()
    assert body["progress_pct"] <= 100.0, body

    # Confirm the same number surfaces in /me/enrollments
    enrollments = await client.get("/api/v1/me/enrollments", headers=student)
    row = next(e for e in enrollments.json() if e["course"]["id"] == course_id)
    assert row["progress_pct"] <= 100.0


async def test_cohort_progress_stays_under_100_after_lesson_soft_delete(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, l1, l2 = await _publish_with_two_lessons(client, teacher, subject.id)

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    await client.post(
        f"/api/v1/me/progress/lessons/{l1}", json={"completed": True}, headers=student
    )
    await client.post(
        f"/api/v1/me/progress/lessons/{l2}", json={"completed": True}, headers=student
    )
    await client.delete(f"/api/v1/courses/lessons/{l1}", headers=teacher)

    cohort = await client.get(f"/api/v1/courses/{course_id}/students", headers=teacher)
    row = cohort.json()[0]
    assert row["progress_pct"] <= 100.0


async def test_per_course_analytics_avg_progress_stays_under_100(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, l1, l2 = await _publish_with_two_lessons(client, teacher, subject.id)

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    await client.post(
        f"/api/v1/me/progress/lessons/{l1}", json={"completed": True}, headers=student
    )
    await client.post(
        f"/api/v1/me/progress/lessons/{l2}", json={"completed": True}, headers=student
    )
    await client.delete(f"/api/v1/courses/lessons/{l1}", headers=teacher)

    analytics = await client.get(f"/api/v1/courses/{course_id}/analytics", headers=teacher)
    assert analytics.json()["avg_progress_pct"] <= 100.0
