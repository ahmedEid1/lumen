"""S3.9 — owner self-learn on a private draft + is_self cert suppression.

FR-LEARN-01 / R-M8'. The owner of a ``visibility=private, status=draft`` course
can learn from it (``can_learn_in_course`` returns True via the owner bypass);
a non-owner cannot (404). A self-enrollment is marked ``is_self`` and
``_maybe_issue_certificate`` short-circuits on it, so completing your own course
mints NO certificate — while a normal learner enrollment still does (regression).

Consumes S4's ``Enrollment.is_self`` + ``enroll_self`` + the cert-suppression
guard (verified landed in git log: commit 39e7ccd).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Enrollment,
    Lesson,
    LessonType,
    Module,
    Subject,
    Visibility,
)
from app.models.user import Role
from app.services import enrollment as enrollment_service
from app.services import visibility as visibility_service

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _pin_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _private_draft_with_one_lesson(
    db: AsyncSession, *, owner_id: str
) -> tuple[Course, Lesson]:
    suffix = uuid.uuid4().hex[:6]
    subj = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subj)
    await db.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subj.id,
        title="My private course",
        slug=f"priv-{suffix}",
        overview="o",
        status=CourseStatus.draft,
        visibility=Visibility.private,
    )
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="M1", description="", order=0)
    db.add(module)
    await db.flush()
    lesson = Lesson(
        module_id=module.id,
        title="L1",
        order=0,
        type=LessonType.text,
        data={"type": "text", "body_markdown": "hi"},
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(course)
    await db.refresh(lesson)
    return course, lesson


# ---------- can_learn_in_course (FR-LEARN-01) ----------


async def test_owner_can_learn_private_draft(db_session: AsyncSession, make_user) -> None:
    owner = await make_user(role=Role.instructor)
    course, _ = await _private_draft_with_one_lesson(db_session, owner_id=owner.id)
    assert await visibility_service.can_learn_in_course(db_session, course, owner) is True


async def test_non_owner_cannot_learn_private_draft(db_session: AsyncSession, make_user) -> None:
    owner = await make_user(role=Role.instructor)
    stranger = await make_user(role=Role.instructor)
    course, _ = await _private_draft_with_one_lesson(db_session, owner_id=owner.id)
    assert await visibility_service.can_learn_in_course(db_session, course, stranger) is False


# ---------- self-enroll marks is_self + suppresses cert (R-M8') ----------


async def test_owner_self_enroll_marks_is_self(db_session: AsyncSession, make_user) -> None:
    owner = await make_user(role=Role.instructor)
    course, _ = await _private_draft_with_one_lesson(db_session, owner_id=owner.id)
    enrollment = await enrollment_service.enroll(db_session, user=owner, course=course)
    assert enrollment.is_self is True


async def test_self_enroll_completion_mints_no_certificate(
    db_session: AsyncSession, make_user
) -> None:
    owner = await make_user(role=Role.instructor)
    course, lesson = await _private_draft_with_one_lesson(db_session, owner_id=owner.id)
    enrollment = await enrollment_service.enroll(db_session, user=owner, course=course)
    assert enrollment.is_self is True

    # Complete the only lesson → all lessons done.
    _, _, pct = await enrollment_service.mark_lesson(
        db_session, user=owner, lesson=lesson, completed=True
    )
    await db_session.refresh(enrollment)
    assert pct == 100.0
    # R-M8': a self-enrollment never mints a certificate/badge.
    assert enrollment.certificate_id is None
    assert enrollment.badge_credential is None


async def test_normal_learner_completion_still_mints(db_session: AsyncSession, make_user) -> None:
    """Regression: a non-self enrollment that completes still mints a certificate."""
    owner = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    course, lesson = await _private_draft_with_one_lesson(db_session, owner_id=owner.id)
    # Publish + share so the learner can enroll as a normal (non-self) learner.
    course.status = CourseStatus.published
    course.visibility = Visibility.public
    from app.models.course import ModerationState

    course.moderation_state = ModerationState.approved
    await db_session.commit()

    enrollment = await enrollment_service.enroll(db_session, user=learner, course=course)
    assert enrollment.is_self is False
    _, _, pct = await enrollment_service.mark_lesson(
        db_session, user=learner, lesson=lesson, completed=True
    )
    await db_session.refresh(enrollment)
    assert pct == 100.0
    assert enrollment.certificate_id is not None  # normal learner DOES get a cert


# ---------- self-enroll idempotency ----------


async def test_self_enroll_idempotent(db_session: AsyncSession, make_user) -> None:
    owner = await make_user(role=Role.instructor)
    course, _ = await _private_draft_with_one_lesson(db_session, owner_id=owner.id)
    e1 = await enrollment_service.enroll(db_session, user=owner, course=course)
    e2 = await enrollment_service.enroll(db_session, user=owner, course=course)
    assert e1.id == e2.id
    # Exactly one enrollment row.
    from sqlalchemy import func, select

    n = (
        await db_session.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.user_id == owner.id, Enrollment.course_id == course.id
            )
        )
    ).scalar_one()
    assert n == 1
