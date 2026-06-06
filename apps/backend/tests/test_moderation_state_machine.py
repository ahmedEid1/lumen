"""S2.9 — owner-intent lifecycle + share state machine (ADR-0026 §4).

DB-backed (runs under ``make test.api``). One assertion cluster per owner
transition row: publish, unpublish (force-private + sticky moderation_state),
share (pending_review + ModerationEvent + classifier fail-closed-never-approve),
re-share R-M9 (prior approval → approved; prior reject/delist → pending_review),
unshare (sticky moderation_state), resubmit (rejected/delisted → pending_review).

Admin-authority transitions (approve/reject/delist/relist/remove) are S6's and
are NOT exercised here.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, ModerationState, Visibility
from app.models.moderation import ModerationEvent
from app.services import courses as courses_service


async def _owner(db):
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    u = User(
        email=f"o-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="O",
        role=Role.instructor,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _course(db, owner, *, status=CourseStatus.draft, with_lesson=True):
    from app.models.course import Lesson as LessonModel
    from app.models.course import LessonType, Module, Subject

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
        visibility=Visibility.private,
        moderation_state=ModerationState.none,
    )
    db.add(course)
    await db.flush()
    if with_lesson:
        module = Module(course_id=course.id, title="M", order=0)
        db.add(module)
        await db.flush()
        db.add(
            LessonModel(
                module_id=module.id,
                title="L",
                order=0,
                type=LessonType.text,
                data={"type": "text", "body_markdown": "x"},
            )
        )
    await db.commit()
    await db.refresh(course)
    return course


@pytest.mark.asyncio
async def test_publish_keeps_private(db_session: AsyncSession):
    owner = await _owner(db_session)
    course = await _course(db_session, owner)
    await courses_service.publish_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.status) == "published"
    assert str(course.visibility) == "private"  # publish does NOT make it public


@pytest.mark.asyncio
async def test_unpublish_forces_private_sticky_moderation(db_session: AsyncSession):
    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    course.visibility = Visibility.public
    course.moderation_state = ModerationState.approved
    course.is_featured = True
    await db_session.commit()

    await courses_service.unpublish_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.status) == "draft"
    assert str(course.visibility) == "private"
    assert course.is_featured is False
    # moderation_state is sticky — NOT reset to none (R-C2)
    assert str(course.moderation_state) == "approved"


@pytest.mark.asyncio
async def test_share_requires_published(db_session: AsyncSession):
    from app.core.errors import ValidationAppError

    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.draft)
    with pytest.raises(ValidationAppError):
        await courses_service.share_course(db_session, course_id=course.id, owner=owner)


@pytest.mark.asyncio
async def test_share_sets_pending_review_and_event(db_session: AsyncSession):
    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    await courses_service.share_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.visibility) == "public"
    assert str(course.moderation_state) == "pending_review"  # never auto-approved (R-C1′)

    events = (
        (
            await db_session.execute(
                select(ModerationEvent).where(ModerationEvent.course_id == course.id)
            )
        )
        .scalars()
        .all()
    )
    assert any(e.to_state == "pending_review" for e in events)
    # classifier signal present + advisory-only
    ev = next(e for e in events if e.to_state == "pending_review")
    assert ev.classifier_signal is not None
    assert ev.classifier_signal.get("advisory_only") is True


@pytest.mark.asyncio
async def test_reshare_with_prior_approval_returns_approved(db_session: AsyncSession):
    """R-M9: a prior approval with no later reject/delist re-approves on share."""
    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    # seed a prior approval event
    db_session.add(
        ModerationEvent(course_id=course.id, from_state="pending_review", to_state="approved")
    )
    await db_session.commit()

    await courses_service.share_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.moderation_state) == "approved"


@pytest.mark.asyncio
async def test_reshare_with_prior_reject_returns_pending(db_session: AsyncSession):
    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    db_session.add(
        ModerationEvent(course_id=course.id, from_state="pending_review", to_state="approved")
    )
    await db_session.flush()
    db_session.add(ModerationEvent(course_id=course.id, from_state="approved", to_state="rejected"))
    await db_session.commit()

    await courses_service.share_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.moderation_state) == "pending_review"


@pytest.mark.asyncio
async def test_unshare_sticky_moderation(db_session: AsyncSession):
    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    course.visibility = Visibility.public
    course.moderation_state = ModerationState.approved
    await db_session.commit()

    await courses_service.unshare_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.visibility) == "private"
    # sticky — NOT reset to none (corrects spec L457)
    assert str(course.moderation_state) == "approved"


@pytest.mark.asyncio
async def test_resubmit_rejected_to_pending(db_session: AsyncSession):
    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    course.visibility = Visibility.public
    course.moderation_state = ModerationState.rejected
    await db_session.commit()

    await courses_service.resubmit_course(db_session, course_id=course.id, owner=owner)
    await db_session.refresh(course)
    assert str(course.moderation_state) == "pending_review"


@pytest.mark.asyncio
async def test_resubmit_rejects_non_rejected(db_session: AsyncSession):
    from app.core.errors import ValidationAppError

    owner = await _owner(db_session)
    course = await _course(db_session, owner, status=CourseStatus.published)
    course.visibility = Visibility.public
    course.moderation_state = ModerationState.pending_review
    await db_session.commit()
    with pytest.raises(ValidationAppError):
        await courses_service.resubmit_course(db_session, course_id=course.id, owner=owner)
