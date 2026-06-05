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


# ---------- GET /me/briefs/{brief_id}/course (Gate-B F1 poll target) ----------


async def _finalized_brief(db: AsyncSession, *, owner_id: str):
    from datetime import UTC, datetime

    from app.core import secrets_crypto
    from app.models.learning_brief import LearningBrief

    brief = LearningBrief(
        owner_id=owner_id,
        source_goal_enc=secrets_crypto.encrypt(b"learn x"),
        goal_summary="Learn X.",
        level="beginner",
        prior_knowledge="some",
        time_budget_hours=10,
        desired_outcomes=["Do X"],
        finalized_at=datetime.now(UTC),
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


async def _ensure_personal_subject(db: AsyncSession) -> None:
    """Seed the reserved Personal subject the shell materializer falls back to."""
    from app.repositories import courses as courses_repo

    slug = get_settings().personal_subject_slug
    if await courses_repo.get_subject_by_slug(db, slug) is None:
        db.add(Subject(title="Personal", slug=slug))
        await db.commit()


async def test_brief_course_status_returns_shell(client, db_session, auth_headers) -> None:
    """While building, the owner can poll the brief→course shell to get the cancel
    target + status (Gate-B F1). The shell is committed before the pipeline lands."""
    from app.models.user import User
    from app.services import build as build_service

    headers = await auth_headers()
    me = await client.get("/api/v1/auth/me", headers=headers)
    uid = me.json()["id"]
    user = await db_session.get(User, uid)
    await _ensure_personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=uid)

    # Materialize the in-flight shell (what the build does before the pipeline).
    shell_id = await build_service._materialize_build_shell(user=user, brief_id=brief.id)

    r = await client.get(f"/api/v1/me/briefs/{brief.id}/course", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["course_id"] == shell_id
    assert body["status"] == "draft"


async def test_brief_course_status_404_before_shell(client, db_session, auth_headers) -> None:
    """No shell yet (build hasn't started) → 404; the UI treats it as 'spinning up'."""
    headers = await auth_headers()
    me = await client.get("/api/v1/auth/me", headers=headers)
    uid = me.json()["id"]
    brief = await _finalized_brief(db_session, owner_id=uid)

    r = await client.get(f"/api/v1/me/briefs/{brief.id}/course", headers=headers)
    assert r.status_code == 404, r.text


async def test_brief_course_status_anonymous_401(client, db_session, make_user) -> None:
    user = await make_user(role=Role.instructor)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    r = await client.get(f"/api/v1/me/briefs/{brief.id}/course")
    assert r.status_code == 401, r.text


async def test_brief_course_status_non_owner_404(client, db_session, auth_headers, make_user) -> None:
    """Another user's brief is existence-hidden (404)."""
    owner = await make_user(role=Role.instructor)
    await _ensure_personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=owner.id)
    from app.models.user import User
    from app.services import build as build_service

    owner_obj = await db_session.get(User, owner.id)
    await build_service._materialize_build_shell(user=owner_obj, brief_id=brief.id)

    headers = await auth_headers()  # a DIFFERENT logged-in user
    r = await client.get(f"/api/v1/me/briefs/{brief.id}/course", headers=headers)
    assert r.status_code == 404, r.text


async def test_cancel_via_polled_shell_id_then_fence_aborts(db_session: AsyncSession, make_user) -> None:
    """Cancel-mid-build via the polled shell id flips it to build_failed and the
    pipeline's per-lesson fence then aborts (Gate-B F1 + R-S10 end-to-end)."""
    from app.core.errors import AccessRevokedError
    from app.models.user import User
    from app.services import authoring_orchestrator as orch
    from app.services import build as build_service

    user = await make_user(role=Role.instructor)
    suffix = uuid.uuid4().hex[:6]
    subj = Subject(title=f"Personal {suffix}", slug=get_settings().personal_subject_slug)
    db_session.add(subj)
    await db_session.commit()
    brief = await _finalized_brief(db_session, owner_id=user.id)
    user_obj = await db_session.get(User, user.id)

    # The build materializes the shell; the UI polls brief_course_status to get it.
    shell_id = await build_service._materialize_build_shell(user=user_obj, brief_id=brief.id)
    polled = await build_service.brief_course_status(db_session, owner_id=user.id, brief_id=brief.id)
    assert polled is not None and polled[0] == shell_id

    # Healthy fence before cancel.
    await db_session.commit()  # ensure shell visible to the fence's own read
    await orch._assert_build_not_cancelled(db_session, shell_id)

    # Cancel via the polled id → flips to build_failed → the fence aborts.
    await courses_service.cancel_build(db_session, course_id=shell_id, owner=user_obj)
    with pytest.raises(AccessRevokedError):
        await orch._assert_build_not_cancelled(db_session, shell_id)


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
