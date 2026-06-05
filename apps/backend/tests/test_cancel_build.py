"""S3.8 — POST /me/courses/{id}/cancel-build (DR-1a / FR-DEFINE-14a).

An explicit owner cancel that transitions an in-flight/abandoned build draft to
``build_failed``, flags it for the S3.10 sweep, and writes ONE audit event. The
cooperative-cancel fence (R-S10): a build job re-reading the course status at a
phase boundary sees ``build_failed`` and aborts. Auth matrix: owner 200,
non-owner 404 (existence-hide), anonymous 401, idempotent re-cancel 200 with no
duplicate audit.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.audit import AuditEvent
from app.models.course import Course, CourseStatus, Subject, Visibility
from app.models.user import Role
from app.services import courses as courses_service

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _pin_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _draft_course(db: AsyncSession, *, owner_id: str) -> Course:
    suffix = uuid.uuid4().hex[:6]
    subj = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subj)
    await db.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subj.id,
        title="In-flight build",
        slug=f"inflight-{suffix}",
        overview="",
        status=CourseStatus.draft,
        visibility=Visibility.private,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


# ---------- Service-level ----------


async def test_cancel_build_transitions_and_audits(db_session: AsyncSession, make_user) -> None:
    user = await make_user(role=Role.instructor)
    course = await _draft_course(db_session, owner_id=user.id)

    await courses_service.cancel_build(db_session, course_id=course.id, owner=user)
    await db_session.refresh(course)
    assert course.status == CourseStatus.build_failed
    assert course.visibility == Visibility.private

    audits = (
        await db_session.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "course.build_cancelled",
                AuditEvent.target_id == course.id,
            )
        )
    ).scalar_one()
    assert audits == 1


async def test_cancel_build_idempotent_no_duplicate_audit(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(role=Role.instructor)
    course = await _draft_course(db_session, owner_id=user.id)

    await courses_service.cancel_build(db_session, course_id=course.id, owner=user)
    await courses_service.cancel_build(db_session, course_id=course.id, owner=user)
    await db_session.refresh(course)
    assert course.status == CourseStatus.build_failed

    audits = (
        await db_session.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "course.build_cancelled",
                AuditEvent.target_id == course.id,
            )
        )
    ).scalar_one()
    assert audits == 1  # idempotent: no duplicate audit


async def test_cancel_build_non_owner_404(db_session: AsyncSession, make_user) -> None:
    owner = await make_user(role=Role.instructor)
    other = await make_user(role=Role.instructor)
    course = await _draft_course(db_session, owner_id=owner.id)

    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await courses_service.cancel_build(db_session, course_id=course.id, owner=other)


# ---------- Endpoint ----------


async def test_endpoint_owner_200(client, db_session, auth_headers) -> None:
    headers = await auth_headers()
    me = await client.get("/api/v1/auth/me", headers=headers)
    uid = me.json()["id"]
    course = await _draft_course(db_session, owner_id=uid)

    r = await client.post(f"/api/v1/me/courses/{course.id}/cancel-build", headers=headers)
    assert r.status_code == 200, r.text
    await db_session.refresh(course)
    assert course.status == CourseStatus.build_failed


async def test_endpoint_anonymous_401(client, db_session, make_user) -> None:
    user = await make_user(role=Role.instructor)
    course = await _draft_course(db_session, owner_id=user.id)
    r = await client.post(f"/api/v1/me/courses/{course.id}/cancel-build")
    assert r.status_code == 401, r.text


async def test_endpoint_non_owner_404(client, db_session, auth_headers, make_user) -> None:
    owner = await make_user(role=Role.instructor)
    course = await _draft_course(db_session, owner_id=owner.id)
    headers = await auth_headers()  # a different (logged-in) user
    r = await client.post(f"/api/v1/me/courses/{course.id}/cancel-build", headers=headers)
    assert r.status_code == 404, r.text


# ---------- Cooperative-cancel fence (R-S10) ----------


async def test_build_fence_aborts_when_cancelled(db_session: AsyncSession, make_user) -> None:
    """A build job re-reading the status at its phase fence aborts once the course
    is flipped to build_failed (the signal cancel-build writes)."""
    from app.core.errors import AccessRevokedError
    from app.services import authoring_orchestrator as orch

    user = await make_user(role=Role.instructor)
    course = await _draft_course(db_session, owner_id=user.id)

    # Healthy draft → fence passes.
    await orch._assert_build_not_cancelled(db_session, course.id)

    # Owner cancels → status flips → the same fence now aborts the build.
    await courses_service.cancel_build(db_session, course_id=course.id, owner=user)
    with pytest.raises(AccessRevokedError):
        await orch._assert_build_not_cancelled(db_session, course.id)
