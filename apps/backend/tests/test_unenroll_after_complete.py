"""Regression: a completed enrollment cannot be unenrolled.

Before iteration 44 ``DELETE /api/v1/me/enrollments/{course_id}``
issued a hard ``db.delete(enrollment)`` regardless of completion
state. The Enrollment row owns the learner's ``certificate_id`` and
all their ``lesson_progress`` rows (FK ondelete=CASCADE), so a single
DELETE silently:

* invalidated the certificate (``/verify/{cert_id}`` → 404),
* threw away every lesson-completion timestamp,
* lost the quiz scores stored on lesson_progress.score and the
  full attempt history on quiz_attempts.

Even though no frontend surface currently exposes unenroll, the API
client does — and once it gets called for a completed enrollment the
damage is permanent. We now refuse with 409 ``enrollment.completed``
and tell the learner to talk to support if they really need the
record removed. Mid-progress unenroll still works as before so a
learner who decided the course wasn't for them can clean up their
dashboard.
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


async def _publish_one_lesson_course(
    client: AsyncClient, teacher: dict, subject_id: str, seed_lesson
) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Done!", "subject_id": subject_id, "overview": "x"},
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


async def test_unenroll_blocked_after_completion(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _publish_one_lesson_course(
        client, teacher, subject.id, seed_lesson
    )

    # Enroll and finish the (single) lesson — earns the certificate.
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    mark = await client.post(
        f"/api/v1/me/progress/lessons/{lesson_id}",
        json={"completed": True},
        headers=student,
    )
    assert mark.status_code == 200
    cert_id = mark.json()["certificate_id"]
    assert cert_id is not None

    # The cert verifies cleanly while the enrollment is intact.
    pre = await client.get(f"/api/v1/certificates/verify/{cert_id}")
    assert pre.status_code == 200

    # Attempting to unenroll is refused.
    drop = await client.delete(
        f"/api/v1/me/enrollments/{course_id}", headers=student
    )
    assert drop.status_code == 409, drop.text
    assert drop.json()["error"]["code"] == "enrollment.completed"

    # And the cert still verifies — the rejected unenroll didn't
    # half-apply (no row was deleted, no cascade fired).
    post = await client.get(f"/api/v1/certificates/verify/{cert_id}")
    assert post.status_code == 200


async def test_mid_progress_unenroll_still_works(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, _ = await _publish_one_lesson_course(
        client, teacher, subject.id, seed_lesson
    )

    # Enroll but don't complete.
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    listed = await client.get("/api/v1/me/enrollments", headers=student)
    assert any(e["course"]["id"] == course_id for e in listed.json())

    drop = await client.delete(
        f"/api/v1/me/enrollments/{course_id}", headers=student
    )
    assert drop.status_code == 200

    # Gone from the dashboard.
    after = await client.get("/api/v1/me/enrollments", headers=student)
    assert all(e["course"]["id"] != course_id for e in after.json())


async def test_unenroll_when_never_enrolled_is_idempotent_ok(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Existing behaviour: unenrolling something you were never on is a noop.

    The endpoint returns 200 OK; we just want to confirm the new branch
    doesn't accidentally turn this into a 4xx.
    """
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, _ = await _publish_one_lesson_course(
        client, teacher, subject.id, seed_lesson
    )

    drop = await client.delete(
        f"/api/v1/me/enrollments/{course_id}", headers=student
    )
    assert drop.status_code == 200
