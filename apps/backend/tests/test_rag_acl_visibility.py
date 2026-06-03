"""S2.7 — cross-course RAG/planner readers route through retrieval_acl_clause.

DB-backed (runs under ``make test.api``). User A's planner/researcher reads may
surface A's own private course + any publicly-listed course, but NEVER user B's
private course. A ``None`` requesting user (system context) collapses to the
listed clause only.

These assert the SQL ACL boundary directly via the central clause over a seeded
mixed table (the same predicate the learning-path/researcher readers now use),
plus a guard that those reader functions actually accept + forward the user id.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, ModerationState, Visibility
from app.services import visibility as vis


async def _owner(db: AsyncSession):
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


async def _subject(db):
    from app.models.course import Subject

    s = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _course(db, owner, subject, *, visibility, status, moderation_state):
    c = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"C {uuid.uuid4().hex[:6]}",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="",
        visibility=visibility,
        status=status,
        moderation_state=moderation_state,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@pytest.mark.asyncio
async def test_cross_course_never_leaks_other_users_private(db_session: AsyncSession):
    subject = await _subject(db_session)
    a = await _owner(db_session)
    b = await _owner(db_session)

    a_private = await _course(
        db_session,
        a,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    public = await _course(
        db_session,
        b,
        subject,
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
    )
    b_private = await _course(
        db_session,
        b,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )

    ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(a.id)))
        ).all()
    }
    assert a_private.id in ids  # own private -> eligible for A's RAG
    assert public.id in ids  # publicly listed -> eligible
    assert b_private.id not in ids  # B's private -> NEVER leaks to A


@pytest.mark.asyncio
async def test_none_viewer_listed_only(db_session: AsyncSession):
    subject = await _subject(db_session)
    a = await _owner(db_session)
    a_private = await _course(
        db_session,
        a,
        subject,
        visibility=Visibility.private,
        status=CourseStatus.draft,
        moderation_state=ModerationState.none,
    )
    ids = {
        row[0]
        for row in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(None)))
        ).all()
    }
    assert a_private.id not in ids


# --------------------------------------------------------------------------
# Structural (pure-unit): the migrated readers carry + forward the user id.
# --------------------------------------------------------------------------


def test_learning_path_readers_take_requesting_user_id():
    from app.services import learning_path as lp

    for fn in (lp._condense_catalog, lp._fallback_recent_published, lp._first_lesson_for_slug):
        assert "requesting_user_id" in inspect.signature(fn).parameters, fn.__name__


def test_researcher_readers_take_requesting_user_id():
    from app.services.authoring_subagents import researcher as r

    for fn in (r._fetch_catalog_neighbours, r._fallback_recent_published, r.run_researcher):
        assert "requesting_user_id" in inspect.signature(fn).parameters, fn.__name__


def test_migrated_readers_no_raw_status_clause():
    """The migrated readers reference retrieval_acl_clause, not raw status."""
    from app.services import learning_path as lp
    from app.services.authoring_subagents import researcher as r

    for src in (
        inspect.getsource(lp._condense_catalog),
        inspect.getsource(lp._fallback_recent_published),
        inspect.getsource(r._fetch_catalog_neighbours),
        inspect.getsource(r._fallback_recent_published),
    ):
        assert "retrieval_acl_clause" in src
        assert "CourseStatus.published" not in src
