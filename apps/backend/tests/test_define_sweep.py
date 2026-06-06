"""S3.10 — define beat sweeps (DR-1b / FR-DEFINE-14b).

Two idempotent reapers driven directly through their async helpers (mirroring
``tutor_sweep._sweep_async``):

* ``sweep_orphaned_build_drafts`` — soft-deletes ``build_failed`` / brief-linked
  draft courses the owner never opened (no LessonProgress) older than the
  retention window. A recently-opened/edited draft and a fresh one are left alone.
* ``sweep_unfinalized_briefs`` — reaps ``finalized_at IS NULL`` briefs older than
  the window; finalized + recent un-finalized briefs are untouched.

Both are idempotent against empty / already-swept state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Enrollment,
    Lesson,
    LessonProgress,
    LessonType,
    Module,
    Subject,
    Visibility,
)
from app.models.course_draft_trace import CourseDraftTrace
from app.models.learning_brief import LearningBrief
from app.workers.tasks import define_sweep

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _pin_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _subject(db: AsyncSession) -> Subject:
    suffix = uuid.uuid4().hex[:6]
    subj = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subj)
    await db.flush()
    return subj


async def _course(
    db: AsyncSession,
    *,
    owner_id: str,
    subject_id: str,
    status: CourseStatus,
    brief_id: str | None = None,
    age_days: int = 0,
) -> Course:
    suffix = uuid.uuid4().hex[:6]
    course = Course(
        owner_id=owner_id,
        subject_id=subject_id,
        title="C",
        slug=f"c-{suffix}",
        overview="",
        status=status,
        visibility=Visibility.private,
    )
    db.add(course)
    await db.flush()
    if brief_id is not None:
        db.add(
            CourseDraftTrace(
                draft_id=f"d-{suffix}",
                course_id=course.id,
                user_id=owner_id,
                step="researcher",
                step_index=0,
                payload={"brief_id": brief_id},
                duration_ms=0,
                status="ok",
            )
        )
    await db.flush()
    if age_days:
        old = datetime.now(UTC) - timedelta(days=age_days)
        # Age BOTH created_at and updated_at: a truly-abandoned build artifact is
        # old in both. The sweep now requires updated_at older than the window too
        # (FR-DEFINE-14b "edited recently is left alone" / Gate-B F2), so a test of
        # the abandoned path must age updated_at as well.
        await db.execute(
            update(Course).where(Course.id == course.id).values(created_at=old, updated_at=old)
        )
    await db.commit()
    await db.refresh(course)
    return course


# ---------- sweep_orphaned_build_drafts ----------


async def test_old_build_failed_orphan_soft_deleted(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    subj = await _subject(db_session)
    await db_session.commit()
    retention = get_settings().orphan_build_draft_retention_days
    course = await _course(
        db_session,
        owner_id=user.id,
        subject_id=subj.id,
        status=CourseStatus.build_failed,
        age_days=retention + 5,
    )

    n = await define_sweep._sweep_orphaned_build_drafts_async()
    assert n >= 1
    await db_session.refresh(course)
    assert course.deleted_at is not None


async def test_recently_opened_draft_left_alone(db_session: AsyncSession, make_user) -> None:
    """A build draft the owner DID open (has LessonProgress) is not swept even if old."""
    user = await make_user()
    subj = await _subject(db_session)
    await db_session.commit()
    retention = get_settings().orphan_build_draft_retention_days
    brief_id = uuid.uuid4().hex
    course = await _course(
        db_session,
        owner_id=user.id,
        subject_id=subj.id,
        status=CourseStatus.draft,
        brief_id=brief_id,
        age_days=retention + 5,
    )
    # The owner opened it: create an enrollment + lesson progress.
    module = Module(course_id=course.id, title="M", description="", order=0)
    db_session.add(module)
    await db_session.flush()
    lesson = Lesson(
        module_id=module.id, title="L", order=0, type=LessonType.text, data={"type": "text"}
    )
    db_session.add(lesson)
    await db_session.flush()
    enr = Enrollment(user_id=user.id, course_id=course.id, is_self=True)
    db_session.add(enr)
    await db_session.flush()
    db_session.add(LessonProgress(enrollment_id=enr.id, lesson_id=lesson.id))
    await db_session.commit()

    await define_sweep._sweep_orphaned_build_drafts_async()
    await db_session.refresh(course)
    assert course.deleted_at is None  # opened → left alone


async def test_old_but_recently_edited_draft_left_alone(
    db_session: AsyncSession, make_user
) -> None:
    """A draft CREATED long ago but EDITED recently survives (Gate-B F2).

    A learner can edit a build draft in studio for weeks without self-enrolling,
    so it has no LessonProgress — the never-opened arm alone would reap it. The
    updated_at guard (FR-DEFINE-14b "edited recently is left alone") spares it: the
    course is old by created_at but its updated_at is inside the window.
    """
    user = await make_user()
    subj = await _subject(db_session)
    await db_session.commit()
    retention = get_settings().orphan_build_draft_retention_days
    brief_id = uuid.uuid4().hex
    # Create old in BOTH timestamps first (the abandoned baseline), then bump
    # updated_at to NOW to model an edit that just happened.
    course = await _course(
        db_session,
        owner_id=user.id,
        subject_id=subj.id,
        status=CourseStatus.draft,
        brief_id=brief_id,
        age_days=retention + 5,
    )
    await db_session.execute(
        update(Course).where(Course.id == course.id).values(updated_at=datetime.now(UTC))
    )
    await db_session.commit()

    n = await define_sweep._sweep_orphaned_build_drafts_async()
    await db_session.refresh(course)
    assert course.deleted_at is None  # edited recently → left alone
    assert n == 0


async def test_old_but_recently_edited_build_failed_left_alone(
    db_session: AsyncSession, make_user
) -> None:
    """The updated_at guard applies to the build_failed arm too (Gate-B F2)."""
    user = await make_user()
    subj = await _subject(db_session)
    await db_session.commit()
    retention = get_settings().orphan_build_draft_retention_days
    course = await _course(
        db_session,
        owner_id=user.id,
        subject_id=subj.id,
        status=CourseStatus.build_failed,
        age_days=retention + 5,
    )
    await db_session.execute(
        update(Course).where(Course.id == course.id).values(updated_at=datetime.now(UTC))
    )
    await db_session.commit()

    await define_sweep._sweep_orphaned_build_drafts_async()
    await db_session.refresh(course)
    assert course.deleted_at is None  # recently touched → spared on both arms


async def test_fresh_orphan_left_alone(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    subj = await _subject(db_session)
    await db_session.commit()
    course = await _course(
        db_session,
        owner_id=user.id,
        subject_id=subj.id,
        status=CourseStatus.build_failed,
        age_days=0,  # brand new
    )
    await define_sweep._sweep_orphaned_build_drafts_async()
    await db_session.refresh(course)
    assert course.deleted_at is None  # too recent


async def test_orphan_sweep_idempotent(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    subj = await _subject(db_session)
    await db_session.commit()
    retention = get_settings().orphan_build_draft_retention_days
    course = await _course(
        db_session,
        owner_id=user.id,
        subject_id=subj.id,
        status=CourseStatus.build_failed,
        age_days=retention + 5,
    )
    n1 = await define_sweep._sweep_orphaned_build_drafts_async()
    n2 = await define_sweep._sweep_orphaned_build_drafts_async()
    assert n1 >= 1
    assert n2 == 0  # already soft-deleted → not re-processed
    await db_session.refresh(course)
    assert course.deleted_at is not None


# ---------- sweep_unfinalized_briefs ----------


async def _brief(
    db: AsyncSession, *, owner_id: str, finalized: bool, age_days: int
) -> LearningBrief:
    brief = LearningBrief(
        owner_id=owner_id,
        source_goal_enc=secrets_crypto.encrypt(b"goal"),
        goal_summary="g",
        finalized_at=datetime.now(UTC) if finalized else None,
    )
    db.add(brief)
    await db.flush()
    if age_days:
        old = datetime.now(UTC) - timedelta(days=age_days)
        await db.execute(
            update(LearningBrief).where(LearningBrief.id == brief.id).values(created_at=old)
        )
    await db.commit()
    await db.refresh(brief)
    return brief


async def test_old_unfinalized_brief_reaped(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    retention = get_settings().unfinalized_brief_retention_days
    brief = await _brief(db_session, owner_id=user.id, finalized=False, age_days=retention + 5)
    brief_id = brief.id  # capture before the worker session deletes the row

    n = await define_sweep._sweep_unfinalized_briefs_async()
    assert n >= 1
    # The sweep ran in a separate worker session; drop our identity-map copy so
    # the re-read hits the DB rather than returning the cached pre-delete instance.
    db_session.expunge_all()
    gone = await db_session.get(LearningBrief, brief_id)
    assert gone is None  # reaped (hard delete — briefs have no soft-delete column)


async def test_finalized_and_recent_briefs_untouched(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    retention = get_settings().unfinalized_brief_retention_days
    finalized = await _brief(db_session, owner_id=user.id, finalized=True, age_days=retention + 5)
    recent = await _brief(db_session, owner_id=user.id, finalized=False, age_days=0)

    await define_sweep._sweep_unfinalized_briefs_async()
    assert await db_session.get(LearningBrief, finalized.id) is not None
    assert await db_session.get(LearningBrief, recent.id) is not None


async def test_unfinalized_sweep_idempotent(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    retention = get_settings().unfinalized_brief_retention_days
    await _brief(db_session, owner_id=user.id, finalized=False, age_days=retention + 5)
    n1 = await define_sweep._sweep_unfinalized_briefs_async()
    n2 = await define_sweep._sweep_unfinalized_briefs_async()
    assert n1 >= 1
    assert n2 == 0
    remaining = (await db_session.execute(select(func.count(LearningBrief.id)))).scalar_one()
    assert remaining == 0
