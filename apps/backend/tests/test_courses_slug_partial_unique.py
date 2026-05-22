"""Regression: ``courses.slug`` uniqueness ignores soft-deleted rows.

Background — rebuild Fix B3
---------------------------
Lumen soft-deletes courses by stamping ``deleted_at``. Migration 0001
enforced ``slug`` uniqueness globally (``uq_courses_slug`` +
``ix_courses_slug`` unique btree), which meant a tombstoned row kept
its slug forever:

* Instructors could not reuse a freed slug for a new course.
* Restoring a soft-deleted course (clearing ``deleted_at``) could
  collide with whatever live row had since claimed the slug — but
  the collision only surfaced at runtime, not at the moment of
  restore.

Migration 0008 replaces the global unique constraint with a partial
unique index (``uq_courses_slug_live``) gated by
``WHERE deleted_at IS NULL``. Tombstoned rows still hold their slug
as a soft-delete tombstone but no longer block live duplicates; if
two live rows ever both claim the same slug Postgres rejects it
immediately — including at restore time.

This test exercises three properties:

1. A live course with slug ``s`` exists.
2. Soft-deleting it lets a fresh live course also use slug ``s``.
3. Trying to restore the tombstoned row (clearing ``deleted_at``)
   while a live duplicate exists raises ``IntegrityError`` on the
   partial unique index.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, Subject
from app.models.user import Role


async def _seed_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_soft_deleted_slug_can_be_reclaimed_and_restore_collides(
    db_session: AsyncSession, make_user
) -> None:
    teacher = await make_user(role=Role.instructor)
    subject = await _seed_subject(db_session)

    # 1) Create course A with slug "x" and soft-delete it.
    course_a = Course(
        owner_id=teacher.id,
        subject_id=subject.id,
        title="Course A",
        slug="x",
        overview="first",
        status=CourseStatus.draft,
    )
    db_session.add(course_a)
    await db_session.commit()
    await db_session.refresh(course_a)

    course_a.deleted_at = datetime.now(UTC)
    await db_session.commit()

    # 2) Create course B with the same slug — must succeed because
    # the partial unique index ignores tombstoned rows.
    course_b = Course(
        owner_id=teacher.id,
        subject_id=subject.id,
        title="Course B",
        slug="x",
        overview="second",
        status=CourseStatus.draft,
    )
    db_session.add(course_b)
    await db_session.commit()
    await db_session.refresh(course_b)

    assert course_b.id != course_a.id
    assert course_a.deleted_at is not None
    assert course_b.deleted_at is None
    assert course_a.slug == course_b.slug == "x"

    # 3) Restore course A by clearing ``deleted_at``. With a live
    # duplicate already on the slug, the partial unique index now
    # *does* see two live rows sharing the value and must reject
    # the update with IntegrityError.
    course_a.deleted_at = None
    with pytest.raises(IntegrityError):
        await db_session.commit()

    # Leave the session in a clean state for downstream test cleanup.
    await db_session.rollback()
