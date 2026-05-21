"""Regression: an instructor cannot review their own course.

Before iteration 40 the review service required enrollment but did not
check ownership. So an instructor could self-enroll in their own
published course (allowed for previewing the student experience) and
then leave themselves a 5-star review, padding ``avg_rating`` and
catalog sort positions. The notification path already encoded this
case via ``if course.owner_id != author.id`` — proving the codebase
knew about the scenario but didn't reject it.

The fix is one ``ForbiddenError`` at the top of ``reviews.upsert``.
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


async def _publish_owned_course(
    client: AsyncClient, headers: dict, subject_id: str
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Owned", "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = create.json()["id"]
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=headers,
    )
    return course_id


async def test_owner_cannot_review_own_course_even_after_enrolling(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _publish_owned_course(client, teacher, subject.id)

    # The instructor can still enroll in their own course (allowed so they
    # can experience it as a learner does).
    enrolled = await client.post(f"/api/v1/me/enrollments/{course_id}", headers=teacher)
    assert enrolled.status_code in (200, 201)

    # But the review attempt is rejected — both PUT and PATCH paths.
    r_put = await client.put(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 5, "body": "Best course ever (by me)."},
        headers=teacher,
    )
    assert r_put.status_code == 403, r_put.text
    assert r_put.json()["error"]["code"] == "review.self_review"

    r_patch = await client.patch(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 5, "body": "Updating my self-review."},
        headers=teacher,
    )
    assert r_patch.status_code == 403
    assert r_patch.json()["error"]["code"] == "review.self_review"


async def test_avg_rating_not_inflated_by_owner_attempts(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _publish_owned_course(client, teacher, subject.id)

    # Student leaves a 3-star review (the only legitimate one).
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    r = await client.put(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 3, "body": "Good but rough edges."},
        headers=student,
    )
    assert r.status_code == 200

    # Owner tries to bump it with a 5-star self-review.
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=teacher)
    r_bad = await client.put(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 5, "body": "Bumping my avg."},
        headers=teacher,
    )
    assert r_bad.status_code == 403

    # Course detail confirms the rejected review never made it to avg.
    detail = await client.get(f"/api/v1/courses/{course_id}", headers=teacher)
    assert detail.json()["avg_rating"] == 3.0


async def test_other_instructor_can_still_review_when_enrolled(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    # Sanity: the guard targets *self*-ownership only, not the role itself.
    owner = await auth_headers(role=Role.instructor)
    other_teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _publish_owned_course(client, owner, subject.id)

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=other_teacher)
    r = await client.put(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 4, "body": "Solid material."},
        headers=other_teacher,
    )
    assert r.status_code == 200
