"""S4.4 — ``enroll_self`` + certificate suppression on self-enrollment.

A clone owner self-enrolls in their own fresh private draft so they can learn
from + track progress on it (FR-CLONE-16). The normal ``enroll()`` gate rejects
non-publicly-listed courses, so clone MUST use a dedicated ``enroll_self`` that
bypasses it (the owner branch of ADR-0026's ``can_learn_in_course`` authorizes
learning in your own course). Self-enrollment is marked ``is_self=True`` so
``_maybe_issue_certificate`` suppresses cert/badge/notification minting (R-M8').
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import (
    Course,
    CourseStatus,
    Enrollment,
    ModerationState,
    Subject,
    Visibility,
)
from app.models.notification import Notification, NotificationKind
from app.models.user import Role, User
from app.services import enrollment as enrollment_service
from app.services import visibility as visibility_service


async def _seed_owner_and_private_draft(db: AsyncSession) -> tuple[User, Course]:
    owner = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@lumen.test",
        password_hash="x",
        full_name="Clone Owner",
        role=Role.user,
    )
    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:8]}")
    db.add_all([owner, subject])
    await db.flush()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title="My Fresh Clone",
        slug=f"clone-{uuid.uuid4().hex[:8]}",
        overview="",
        status=CourseStatus.draft,
        visibility=Visibility.private,
        moderation_state=ModerationState.none,
    )
    db.add(course)
    await db.commit()
    await db.refresh(owner)
    await db.refresh(course)
    return owner, course


async def _count_notifications(db: AsyncSession, user_id: str, kind: NotificationKind) -> int:
    rows = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.user_id == user_id, Notification.kind == kind
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


async def test_enroll_self_on_private_draft(db_session: AsyncSession) -> None:
    owner, course = await _seed_owner_and_private_draft(db_session)

    # The owner self-preview is allowed by can_enroll, but the enroll() path
    # still creates a "Welcome" notification + no is_self marker — enroll_self is
    # the dedicated, notification-free, is_self path used by clone.
    can, _reason = await visibility_service.can_enroll(db_session, course, owner)
    assert can is True

    en = await enrollment_service.enroll_self(db_session, user=owner, course=course)
    await db_session.flush()
    assert en.is_self is True
    assert en.user_id == owner.id
    assert en.course_id == course.id
    # No "Welcome" notification for a self-enroll.
    assert await _count_notifications(db_session, owner.id, NotificationKind.enrolled) == 0


async def test_enroll_self_bypasses_published_gate(db_session: AsyncSession) -> None:
    """A truly non-enrollable course (private draft, NOT owner via enroll())."""
    owner, course = await _seed_owner_and_private_draft(db_session)
    # enroll_self never reads status/visibility — it just self-enrolls the owner.
    en = await enrollment_service.enroll_self(db_session, user=owner, course=course)
    assert en.is_self is True
    assert course.status == CourseStatus.draft
    assert course.visibility == Visibility.private


async def test_enroll_self_idempotent(db_session: AsyncSession) -> None:
    owner, course = await _seed_owner_and_private_draft(db_session)
    first = await enrollment_service.enroll_self(db_session, user=owner, course=course)
    await db_session.flush()
    second = await enrollment_service.enroll_self(db_session, user=owner, course=course)
    await db_session.flush()
    assert first.id == second.id
    rows = (
        (
            await db_session.execute(
                select(Enrollment).where(
                    Enrollment.user_id == owner.id, Enrollment.course_id == course.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_self_enrollment_no_certificate(db_session: AsyncSession) -> None:
    owner, course = await _seed_owner_and_private_draft(db_session)
    en = await enrollment_service.enroll_self(db_session, user=owner, course=course)
    await db_session.flush()

    # Drive the cert path as if every lesson is complete.
    await enrollment_service._maybe_issue_certificate(
        db_session, user=owner, course=course, enrollment=en, total=3, done=3
    )
    assert en.completed_at is None
    assert en.certificate_id is None
    assert en.badge_credential is None
    assert await _count_notifications(db_session, owner.id, NotificationKind.certificate_ready) == 0


async def test_non_self_enrollment_does_mint(db_session: AsyncSession) -> None:
    """Control: a regular (non-self) enrollment DOES mint a certificate."""
    _owner, course = await _seed_owner_and_private_draft(db_session)
    learner = User(
        email=f"learner-{uuid.uuid4().hex[:8]}@lumen.test",
        password_hash="x",
        full_name="Learner",
        role=Role.user,
    )
    db_session.add(learner)
    await db_session.flush()
    en = Enrollment(user_id=learner.id, course_id=course.id, is_self=False)
    db_session.add(en)
    await db_session.flush()

    await enrollment_service._maybe_issue_certificate(
        db_session, user=learner, course=course, enrollment=en, total=2, done=2
    )
    assert en.completed_at is not None
    assert en.certificate_id is not None
    assert (
        await _count_notifications(db_session, learner.id, NotificationKind.certificate_ready) == 1
    )
