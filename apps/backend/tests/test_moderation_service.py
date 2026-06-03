"""S6.2 — admin-authority moderation transition service (ADR-0026 §4 / S6).

DB-backed (runs under ``make test.api``). One cluster per admin transition:
approve / reject / delist / relist / remove_course, plus the sticky-on-owner-
action cross-check (R-C2). Each transition writes both a ``ModerationEvent``
(durable history) and an ``AuditEvent`` (admin.course.*), sets ``quarantined``
for csam/illegal hard-removal (DR-18-R2), and revokes enrolled access on
hard-removal (R-C6′) while ``severe_abuse`` keeps the owner's view/edit.

The S2 owner-intent side (share/unshare/_transition_status/sticky state) is NOT
re-tested here — only the admin-authority side S6 builds on top.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationAppError
from app.models.audit import AuditEvent
from app.models.course import Course, CourseStatus, ModerationState, Visibility
from app.models.moderation import ModerationEvent
from app.services import courses as courses_service
from app.services import moderation as moderation_service
from app.services.moderation_taxonomy import ReasonCode
from app.services.visibility import can_view_course, is_publicly_listed


async def _admin(db):
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    u = User(
        email=f"admin-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Admin",
        role=Role.admin,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _user(db, *, role=None):
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    u = User(
        email=f"u-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="U",
        role=role or Role.user,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _course(
    db,
    owner,
    *,
    status=CourseStatus.published,
    visibility=Visibility.public,
    moderation_state=ModerationState.pending_review,
    is_featured=False,
):
    from app.models.course import Subject

    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:6]}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"C {uuid.uuid4().hex[:6]}",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="o",
        status=status,
        visibility=visibility,
        moderation_state=moderation_state,
        is_featured=is_featured,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _enroll(db, user, course):
    from app.models.course import Enrollment

    e = Enrollment(user_id=user.id, course_id=course.id)
    db.add(e)
    await db.commit()
    return e


async def _events(db, course_id) -> list[ModerationEvent]:
    res = await db.execute(
        select(ModerationEvent)
        .where(ModerationEvent.course_id == course_id)
        .order_by(ModerationEvent.created_at.asc())
    )
    return list(res.scalars().all())


async def _audits(db, course_id, action) -> list[AuditEvent]:
    res = await db.execute(
        select(AuditEvent).where(AuditEvent.target_id == course_id, AuditEvent.action == action)
    )
    return list(res.scalars().all())


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_lists_and_writes_event(db_session: AsyncSession):
    admin = await _admin(db_session)
    owner = await _user(db_session)
    course = await _course(db_session, owner)

    with patch.object(courses_service, "_schedule_embedding_index") as mock_idx:
        await moderation_service.approve_course(db_session, course_id=course.id, actor=admin)
    await db_session.refresh(course)
    assert str(course.moderation_state) == "approved"
    assert is_publicly_listed(course)
    events = await _events(db_session, course.id)
    assert events and str(events[-1].to_state) == "approved"
    assert events[-1].actor_id == admin.id
    assert await _audits(db_session, course.id, "admin.course.approve")
    # Reindex enqueued (best-effort, mocked) on transition-to-listed.
    mock_idx.assert_called()


@pytest.mark.asyncio
async def test_approve_invalid_source_state(db_session: AsyncSession):
    """Approving a course not in pending_review is an invalid transition."""
    admin = await _admin(db_session)
    owner = await _user(db_session)
    course = await _course(db_session, owner, moderation_state=ModerationState.approved)
    with pytest.raises(ValidationAppError) as ei:
        await moderation_service.approve_course(db_session, course_id=course.id, actor=admin)
    assert ei.value.code == "course.invalid_transition"


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_forces_private(db_session: AsyncSession):
    admin = await _admin(db_session)
    owner = await _user(db_session)
    course = await _course(db_session, owner)
    await moderation_service.reject_course(
        db_session, course_id=course.id, actor=admin, reason=ReasonCode.spam
    )
    await db_session.refresh(course)
    assert str(course.moderation_state) == "rejected"
    assert str(course.visibility) == "private"  # FR-MOD-07
    assert await _audits(db_session, course.id, "admin.course.reject")
    events = await _events(db_session, course.id)
    assert str(events[-1].to_state) == "rejected"


# ---------------------------------------------------------------------------
# delist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delist_not_soft_deleted_and_defeatures(db_session: AsyncSession):
    admin = await _admin(db_session)
    owner = await _user(db_session)
    course = await _course(
        db_session, owner, moderation_state=ModerationState.approved, is_featured=True
    )
    await moderation_service.delist_course(
        db_session, course_id=course.id, actor=admin, reason=ReasonCode.spam
    )
    await db_session.refresh(course)
    assert str(course.moderation_state) == "delisted"
    assert course.is_featured is False
    assert course.deleted_at is None  # owner keeps content (FR-MOD-03)
    first_events = await _events(db_session, course.id)

    # Idempotent: a second delist writes no new event.
    await moderation_service.delist_course(
        db_session, course_id=course.id, actor=admin, reason=ReasonCode.spam
    )
    await db_session.refresh(course)
    assert len(await _events(db_session, course.id)) == len(first_events)


# ---------------------------------------------------------------------------
# relist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relist_409_when_not_listable(db_session: AsyncSession):
    """A delisted-but-now-private course can't relist (predicate wouldn't hold);
    a delisted-but-still-public-published course relists to approved (FR-MOD-04).
    """
    admin = await _admin(db_session)
    owner = await _user(db_session)

    # Now-private delisted course -> 409 course.not_listable.
    private_delisted = await _course(
        db_session,
        owner,
        visibility=Visibility.private,
        moderation_state=ModerationState.delisted,
    )
    with pytest.raises(ConflictError) as ei:
        await moderation_service.relist_course(
            db_session, course_id=private_delisted.id, actor=admin
        )
    assert ei.value.code == "course.not_listable"

    # Still public+published delisted course -> relists to approved.
    public_delisted = await _course(
        db_session,
        owner,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.delisted,
    )
    await moderation_service.relist_course(db_session, course_id=public_delisted.id, actor=admin)
    await db_session.refresh(public_delisted)
    assert str(public_delisted.moderation_state) == "approved"
    assert is_publicly_listed(public_delisted)


# ---------------------------------------------------------------------------
# remove_course — csam (quarantine) vs severe_abuse (owner keeps view)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_csam_sets_quarantined_and_revokes_all(db_session: AsyncSession):
    admin = await _admin(db_session)
    owner = await _user(db_session)
    learner = await _user(db_session)
    course = await _course(db_session, owner, moderation_state=ModerationState.approved)
    await _enroll(db_session, learner, course)

    await moderation_service.remove_course(
        db_session, course_id=course.id, actor=admin, reason=ReasonCode.csam
    )
    await db_session.refresh(course)
    assert course.deleted_at is not None
    assert course.quarantined is True
    # Full quarantine: even the owner and the enrolled learner lose view (R-C6′).
    assert await can_view_course(db_session, course, owner) is False
    assert await can_view_course(db_session, course, learner) is False
    events = await _events(db_session, course.id)
    assert str(events[-1].reason_code) == "csam"
    assert await _audits(db_session, course.id, "admin.course.remove")


@pytest.mark.asyncio
async def test_remove_severe_abuse_owner_keeps_view(db_session: AsyncSession):
    admin = await _admin(db_session)
    owner = await _user(db_session)
    learner = await _user(db_session)
    course = await _course(db_session, owner, moderation_state=ModerationState.approved)
    await _enroll(db_session, learner, course)

    await moderation_service.remove_course(
        db_session, course_id=course.id, actor=admin, reason=ReasonCode.severe_abuse
    )
    await db_session.refresh(course)
    assert course.deleted_at is not None
    assert course.quarantined is False  # NOT quarantined (DR-18-R2)
    # Owner keeps view/edit; other learners revoked (FR-MOD-08).
    assert await can_view_course(db_session, course, owner) is True
    assert await can_view_course(db_session, course, learner) is False


# ---------------------------------------------------------------------------
# sticky moderation_state across an owner action (R-C2 cross-check with S2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_moderation_state_sticky_on_owner_actions(db_session: AsyncSession):
    admin = await _admin(db_session)
    owner = await _user(db_session)
    course = await _course(db_session, owner, moderation_state=ModerationState.approved)
    await moderation_service.delist_course(
        db_session, course_id=course.id, actor=admin, reason=ReasonCode.spam
    )
    await db_session.refresh(course)
    assert str(course.moderation_state) == "delisted"

    # Owner unshare (public->private): moderation_state must stay delisted.
    await courses_service.unshare_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.moderation_state) == "delisted"
    assert str(course.visibility) == "private"
