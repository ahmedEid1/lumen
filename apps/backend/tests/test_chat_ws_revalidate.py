"""Regression: chat WS must re-authorise on every post.

Before iteration 36 the WS handler captured ``user`` and ``course`` once
at connect time and reused them for the lifetime of the socket. That
meant:

* deactivating an account (admin action) didn't cut off in-flight chat;
  the next call could still post because we never re-read ``is_active``;
* unenrolling a learner from a course didn't stop them chatting — the
  same socket kept publishing because the connect-time ``ensure_can_chat``
  result was cached in a local variable;
* unpublishing a course was equally invisible.

The fix is to re-run ``users_repo.get_by_id`` and ``ensure_can_chat`` on
every inbound ``message`` frame and close the socket if either fails.

We don't have a WS test harness in this repo (the existing chat tests
exercise the REST surface), so this test pins the *primitives* the WS
now calls: a freshly-loaded user reflects ``is_active`` changes, and
``ensure_can_chat`` correctly rejects after an unenroll. The WS handler
itself is a 5-line wrapper around these two checks.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.models.course import Course, CourseStatus, Enrollment, Subject
from app.models.user import Role
from app.repositories import courses as courses_repo
from app.repositories import users as users_repo
from app.services import chat as chat_service


async def _seed_student_in_course(db_session: AsyncSession, make_user):
    student = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="x",
        owner_id=teacher.id,
        subject_id=subject.id,
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    db_session.add(Enrollment(user_id=student.id, course_id=course.id))
    await db_session.commit()
    await db_session.refresh(course)
    await db_session.refresh(student)
    return student, course


async def test_fresh_user_load_picks_up_deactivation(db_session, make_user):
    student, course = await _seed_student_in_course(db_session, make_user)
    # Connect-time snapshot — what the WS used to reuse forever.
    snapshot_is_active = student.is_active
    assert snapshot_is_active is True

    # Admin deactivates the account.
    student.is_active = False
    await db_session.commit()

    fresh = await users_repo.get_by_id(db_session, student.id)
    assert fresh is not None
    assert fresh.is_active is False, "stale capture would still see True"


async def test_ensure_can_chat_rejects_after_unenroll(db_session, make_user):
    student, course = await _seed_student_in_course(db_session, make_user)

    # Connect-time check succeeds.
    ok = await chat_service.ensure_can_chat(db_session, user=student, course_id=course.id)
    assert ok.id == course.id

    # Owner/admin removes the enrollment.
    enrollment = await courses_repo.get_enrollment(db_session, user_id=student.id, course_id=course.id)
    assert enrollment is not None
    await db_session.delete(enrollment)
    await db_session.commit()

    with pytest.raises(ForbiddenError) as exc:
        await chat_service.ensure_can_chat(db_session, user=student, course_id=course.id)
    assert exc.value.code == "chat.enroll_first"


async def test_owner_still_allowed_when_their_own_enrollment_is_missing(db_session, make_user):
    # Sanity: the recheck must not flap for the instructor/owner branch,
    # which never had an enrollment to begin with.
    teacher = await make_user(role=Role.instructor)
    subject = Subject(title="Math", slug=f"math-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        title="Owned",
        slug=f"owned-{uuid.uuid4().hex[:6]}",
        overview="x",
        owner_id=teacher.id,
        subject_id=subject.id,
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.commit()

    out = await chat_service.ensure_can_chat(db_session, user=teacher, course_id=course.id)
    assert out.id == course.id
