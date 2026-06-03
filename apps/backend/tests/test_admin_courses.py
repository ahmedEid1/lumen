"""Admin course overview + featured toggle."""

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


async def test_list_courses_requires_admin(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/admin/courses", headers=h)
    assert r.status_code == 403


async def test_admin_can_list_and_filter_courses(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session)
    await client.post(
        "/api/v1/courses",
        json={"title": "Pi", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    await client.post(
        "/api/v1/courses",
        json={"title": "Other", "subject_id": subject.id, "overview": "y"},
        headers=teacher,
    )

    full = await client.get("/api/v1/admin/courses", headers=admin)
    assert full.status_code == 200
    assert len(full.json()) >= 2

    filtered = await client.get("/api/v1/admin/courses?q=Pi", headers=admin)
    assert filtered.status_code == 200
    titles = [c["title"] for c in filtered.json()]
    assert "Pi" in titles
    assert "Other" not in titles


async def test_admin_toggles_featured_and_writes_audit(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Featurable", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    assert create.json()["is_featured"] is False

    feat = await client.patch(
        f"/api/v1/admin/courses/{course_id}/feature",
        json={"is_featured": True},
        headers=admin,
    )
    assert feat.status_code == 200
    assert feat.json()["is_featured"] is True

    # only_featured filter now returns it
    only = await client.get("/api/v1/admin/courses?only_featured=true", headers=admin)
    assert any(c["id"] == course_id for c in only.json())

    # Audit log carries an admin.course.featured event for this course
    audit = await client.get("/api/v1/admin/audit?action=admin.course.featured", headers=admin)
    assert audit.status_code == 200
    assert any(e["target_id"] == course_id for e in audit.json())

    # Idempotent — toggling to the same state does not add another audit row
    again = await client.patch(
        f"/api/v1/admin/courses/{course_id}/feature",
        json={"is_featured": True},
        headers=admin,
    )
    assert again.status_code == 200
    audit2 = await client.get("/api/v1/admin/audit?action=admin.course.featured", headers=admin)
    rows_for_course = [e for e in audit2.json() if e["target_id"] == course_id]
    assert len(rows_for_course) == 1


async def test_feature_unknown_course_404(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.patch(
        "/api/v1/admin/courses/nope/feature",
        json={"is_featured": True},
        headers=admin,
    )
    assert r.status_code == 404


async def test_admin_cannot_edit_others_course(
    client: AsyncClient, auth_headers, db_session
) -> None:
    """FR-MOD-05 / S2.8: an admin may VIEW any course but must NOT mutate a
    non-owned course via the owner-shaped PATCH/DELETE endpoints — admin
    course-state changes go through the moderation endpoints (S6) only.
    Coordinates with S6.5 (which keeps this as its regression test).
    """
    teacher = await auth_headers(role=Role.instructor)
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Owned by teacher", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]

    # Admin CAN view it via the admin listing (any course).
    listing = await client.get("/api/v1/admin/courses", headers=admin)
    assert listing.status_code == 200
    assert any(c["id"] == course_id for c in listing.json())

    # Admin CANNOT PATCH a non-owned course via the owner-shaped endpoint.
    patched = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"overview": "admin edit attempt"},
        headers=admin,
    )
    assert patched.status_code == 403
    assert patched.json()["error"]["code"] == "course.forbidden"

    # Admin CANNOT DELETE a non-owned course via the owner-shaped endpoint.
    deleted = await client.delete(f"/api/v1/courses/{course_id}", headers=admin)
    assert deleted.status_code == 403
    assert deleted.json()["error"]["code"] == "course.forbidden"
