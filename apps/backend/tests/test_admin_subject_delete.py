"""Regression: deleting an admin subject must 409, not 500, when courses use it.

Before iteration 28 the admin delete endpoint issued an unconditional
``DELETE FROM subjects`` for the chosen row. Because
``Course.subject_id`` is ``FK ondelete=RESTRICT``, the DB raised an
``IntegrityError`` which the unhandled-exception path turned into a
generic 500 ``internal_error`` for the operator. The endpoint now
pre-checks and returns a clean 409 ``subject.in_use`` with the count of
attached courses so the admin can clean up first.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession, slug: str = "in-use") -> Subject:
    s = Subject(title="In use", slug=f"{slug}-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_delete_subject_with_attached_course_is_409(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Anchored", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    assert create.status_code == 201

    r = await client.delete(f"/api/v1/admin/subjects/{subject.id}", headers=admin)
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "subject.in_use"
    assert body["error"]["details"]["courses"] >= 1


async def test_soft_deleted_courses_also_block_subject_delete(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """The FK is RESTRICT regardless of ``Course.deleted_at`` — so the
    pre-check must count every row, otherwise the underlying DELETE
    crashes against the constraint and surfaces as a 500."""
    admin = await auth_headers(role=Role.admin)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session, slug="cleanable")

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Soon gone", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await client.delete(f"/api/v1/courses/{course_id}", headers=teacher)

    r = await client.delete(f"/api/v1/admin/subjects/{subject.id}", headers=admin)
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "subject.in_use"
    # The pre-check splits live vs total so the operator can tell at a
    # glance that the blocker is a soft-deleted course.
    assert body["error"]["details"]["courses"] == 0
    assert body["error"]["details"]["courses_including_deleted"] >= 1


async def test_delete_subject_with_no_courses_succeeds(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session, slug="lone")
    r = await client.delete(f"/api/v1/admin/subjects/{subject.id}", headers=admin)
    assert r.status_code == 200


async def test_delete_unknown_subject_is_404(
    client: AsyncClient, auth_headers
) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.delete("/api/v1/admin/subjects/nope", headers=admin)
    assert r.status_code == 404
