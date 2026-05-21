"""Regression: cert PDF download still works after course soft-delete.

Before iteration 45 ``download_certificate`` loaded the course via
``courses_repo.get_course``, which filters ``deleted_at IS NULL``. So
once an instructor (or admin) soft-deleted the course, every learner
who'd earned the cert got a 404 when they tried to download their
PDF — their permanent achievement record was held hostage by an
unrelated content-curation decision.

The public ``verify_certificate`` endpoint already takes the right
posture (no ``deleted_at`` filter on the join), and iteration 44
blocked the *learner* from breaking their own cert via unenroll.
This iteration closes the matching server-side path: the cert PDF
endpoint uses ``db.get(Course, course_id)`` directly so a soft-
deleted course doesn't void an earned credential.
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


async def test_pdf_still_downloads_after_course_soft_delete(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Survives", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    lesson_id = await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    mark = await client.post(
        f"/api/v1/me/progress/lessons/{lesson_id}",
        json={"completed": True},
        headers=student,
    )
    assert mark.status_code == 200
    cert_id = mark.json()["certificate_id"]
    assert cert_id is not None

    # Sanity: PDF downloads cleanly while the course is alive.
    pre = await client.get(f"/api/v1/certificates/{course_id}.pdf", headers=student)
    assert pre.status_code == 200
    assert pre.content.startswith(b"%PDF")

    # Instructor soft-deletes the course (could be content cleanup,
    # IP dispute, course retirement — none of these should void
    # already-earned credentials).
    rm = await client.delete(f"/api/v1/courses/{course_id}", headers=teacher)
    assert rm.status_code == 200

    # The catalog hides the course (as iter 22-23 work expected) …
    catalog = await client.get("/api/v1/courses?page=1&page_size=50")
    assert all(c["id"] != course_id for c in catalog.json()["items"])

    # … but the cert PDF still renders, and verify still works.
    post = await client.get(
        f"/api/v1/certificates/{course_id}.pdf", headers=student
    )
    assert post.status_code == 200, post.text
    assert post.content.startswith(b"%PDF")

    verify = await client.get(f"/api/v1/certificates/verify/{cert_id}")
    assert verify.status_code == 200


async def test_pdf_404_when_course_truly_missing(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Sanity: my soft-delete-tolerant lookup doesn't paper over a
    genuinely-bad course_id either. The endpoint still distinguishes a
    completed-but-course-missing case from a not-enrolled case."""
    student = await auth_headers(role=Role.student)
    r = await client.get(
        "/api/v1/certificates/nope-not-a-real-id.pdf", headers=student
    )
    # Not enrolled is the first guard so this is 403, not 404 — covered
    # to lock down ordering of the checks.
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cert.not_enrolled"
