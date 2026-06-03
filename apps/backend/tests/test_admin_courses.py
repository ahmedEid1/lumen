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

    # S6.4: only a publicly-listed course can be featured — bring it to
    # public+published+approved so the listing guard is satisfied.
    from app.models.course import Course, CourseStatus, ModerationState, Visibility

    course = await db_session.get(Course, course_id)
    course.status = CourseStatus.published
    course.visibility = Visibility.public
    course.moderation_state = ModerationState.approved
    await db_session.commit()

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


# ---------------------------------------------------------------------------
# Moderation queue: active-sharing-intent narrowing (DR-21)
# ---------------------------------------------------------------------------


async def _mk_course_state(
    db: AsyncSession,
    *,
    owner_id: str,
    subject_id: str,
    visibility,
    status,
    moderation_state,
):
    from app.models.course import Course

    c = Course(
        owner_id=owner_id,
        subject_id=subject_id,
        title=f"Q {uuid.uuid4().hex[:6]}",
        slug=f"q-{uuid.uuid4().hex[:8]}",
        overview="",
        visibility=visibility,
        status=status,
        moderation_state=moderation_state,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def test_moderation_queue_only_shows_active_sharing_intent(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession
) -> None:
    """A shared (public+published) pending_review course is in the queue; once
    unshared back to private it drops out while moderation_state stays sticky
    in the DB (DR-21 queue narrowing — only the QUEUE view narrows)."""
    from app.models.course import CourseStatus, ModerationState, Visibility

    admin = await auth_headers(role=Role.admin)
    owner = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    # Shared: public + published + pending_review -> in the queue.
    shared = await _mk_course_state(
        db_session,
        owner_id=owner.id,
        subject_id=subject.id,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.pending_review,
    )
    r = await client.get("/api/v1/admin/courses/moderation-queue", headers=admin)
    assert r.status_code == 200
    assert any(c["id"] == shared.id for c in r.json()), "shared course must be in the queue"

    # Unshare: visibility -> private; moderation_state stays sticky.
    shared.visibility = Visibility.private
    await db_session.commit()

    r2 = await client.get("/api/v1/admin/courses/moderation-queue", headers=admin)
    assert r2.status_code == 200
    assert all(c["id"] != shared.id for c in r2.json()), "unshared course must drop from queue"

    # ...but the sticky moderation_state is preserved in the DB (R-M9 re-share).
    await db_session.refresh(shared)
    assert str(shared.moderation_state) == str(ModerationState.pending_review)
