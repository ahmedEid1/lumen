"""Course status transitions, ownership, soft-delete visibility.

S2 / ADR-0026 moved the publish action off ``PATCH {status}`` (now a 422 —
``CourseUpdate`` is ``extra=forbid``, FR-VIS-08) onto the owner-intent lifecycle
endpoints ``POST /courses/{id}/publish`` and ``/unpublish``. Publishing keeps a
course PRIVATE; only ``visibility==public AND status==published AND
moderation_state==approved AND deleted_at IS NULL`` is publicly listed
(``is_publicly_listed``), so catalog-visibility flows go through the
``publish_and_list_course`` fixture.

The ``archived`` status has no owner-facing HTTP transition in S2 (the owner
lifecycle is publish/unpublish only). The archived↔published state-machine
invariant still lives in ``_transition_status`` in the service layer — which is
where ``CLAUDE.md`` says invariants live — so the invalid-transition case is
pinned at that layer here. Owner-only mutation (FR-MOD-05 / S2.8) is also pinned:
an admin may VIEW any course but must NOT mutate a non-owned course through the
owner-shaped PATCH/DELETE (admin course-state changes go through the moderation
endpoints, S6); the canonical regression for that is
``test_admin_courses.py::test_admin_cannot_edit_others_course``.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.models.course import CourseStatus, Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_invalid_transition_blocked(
    client: AsyncClient, auth_headers, db_session: AsyncSession, publish_course, seed_lesson
) -> None:
    """draft→published→archived is allowed; archived→published is NOT.

    Publish goes through the owner lifecycle endpoint (``POST /publish``). There
    is no owner-facing ``archived`` HTTP transition in S2, so the archived step
    and the rejected archived→published step are driven against the service-layer
    state machine (``_transition_status``), which is where the invariant lives.
    """
    from app.repositories import courses as courses_repo
    from app.services import courses as courses_service

    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "X", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = r.json()["id"]
    await seed_lesson(course_id, teacher)

    # draft → published via the lifecycle endpoint.
    pub = await publish_course(course_id, teacher)
    assert pub.json()["status"] == "published"

    # published → archived is a valid transition (service-layer; no HTTP route).
    course = await courses_repo.get_course(db_session, course_id)
    await courses_service._transition_status(db_session, course, CourseStatus.archived)
    await db_session.commit()
    assert str(course.status) == "archived"

    # archived → published is NOT allowed — the state machine rejects it.
    with pytest.raises(ValidationAppError) as exc:
        await courses_service._transition_status(db_session, course, CourseStatus.published)
    assert exc.value.code == "course.invalid_transition"


async def test_non_owner_cannot_edit_course(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher_a = await auth_headers(role=Role.instructor)
    teacher_b = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Owned", "subject_id": subject.id, "overview": "x"},
        headers=teacher_a,
    )
    course_id = r.json()["id"]
    bad = await client.patch(
        f"/api/v1/courses/{course_id}", json={"title": "Hijacked"}, headers=teacher_b
    )
    assert bad.status_code == 403


async def test_admin_cannot_edit_non_owned_course_via_owner_patch(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """FR-MOD-05 / S2.8: the old ``admin can edit any course`` rule was NARROWED.

    An admin may VIEW any course but must NOT mutate a non-owned course through
    the owner-shaped PATCH endpoint — admin course-state changes go through the
    moderation endpoints (S6) only. The owner-only gate lives in
    ``_can_edit_course`` and returns ``course.forbidden`` for a non-owner admin.
    (Canonical regression: ``test_admin_courses.py::test_admin_cannot_edit_others_course``.)
    """
    teacher = await auth_headers(role=Role.instructor)
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Owned", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = r.json()["id"]
    edit = await client.patch(
        f"/api/v1/courses/{course_id}", json={"title": "Renamed by admin"}, headers=admin
    )
    assert edit.status_code == 403
    assert edit.json()["error"]["code"] == "course.forbidden"

    # The course was NOT renamed — the title is untouched.
    detail = await client.get(f"/api/v1/courses/{course_id}", headers=teacher)
    assert detail.json()["title"] == "Owned"


async def test_soft_delete_hides_from_catalog(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Soon gone", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = r.json()["id"]
    await seed_lesson(course_id, teacher)
    # Publish AND make publicly listed so it actually appears in the catalog.
    await publish_and_list_course(course_id, teacher)

    catalog = await client.get("/api/v1/courses?page=1&page_size=50")
    assert any(c["id"] == course_id for c in catalog.json()["items"])

    deleted = await client.delete(f"/api/v1/courses/{course_id}", headers=teacher)
    assert deleted.status_code == 200

    catalog2 = await client.get("/api/v1/courses?page=1&page_size=50")
    assert all(c["id"] != course_id for c in catalog2.json()["items"])
