"""0052 backfill regression (Codex confirm-round P1).

``_is_successfully_built`` consults ``build_completed_at`` immediately for
replay decisions — without the backfill, a deployment carrying pre-marker
successful builds would see them all as "not built" (re-submits could
overwrite them or flip them to ``build_failed`` on a failing re-run). The
migration stamps every course the OLD heuristic considered built
(non-failed, live, >=1 module). DB-backed: reproduces the pre-marker
state by NULLing the column, runs the migration's backfill statement,
and asserts the stamp landed exactly where the heuristic says.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, Difficulty, Module, Subject, Visibility

_BACKFILL = text(
    """
    UPDATE courses SET build_completed_at = updated_at
    WHERE build_completed_at IS NULL
      AND status != 'build_failed'
      AND deleted_at IS NULL
      AND EXISTS (SELECT 1 FROM modules m WHERE m.course_id = courses.id)
    """
)


async def _course(db: AsyncSession, owner_id: str, *, status, with_module: bool) -> Course:
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subject)
    await db.flush()
    c = Course(
        owner_id=owner_id,
        subject_id=subject.id,
        title=f"C {suffix}",
        slug=f"c-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=status,
        visibility=Visibility.private,
    )
    db.add(c)
    await db.flush()
    if with_module:
        db.add(Module(course_id=c.id, title="M1", order=0))
        await db.flush()
    return c


@pytest.mark.asyncio
async def test_backfill_stamps_old_heuristic_exactly(db_session: AsyncSession, make_user):
    owner = await make_user()
    built = await _course(db_session, owner.id, status=CourseStatus.draft, with_module=True)
    empty_shell = await _course(db_session, owner.id, status=CourseStatus.draft, with_module=False)
    failed = await _course(db_session, owner.id, status=CourseStatus.build_failed, with_module=True)
    # Capture before expire_all — expired ORM attribute access in async ctx
    # raises MissingGreenlet (sync lazy-load).
    built_id, shell_id, failed_id = built.id, empty_shell.id, failed.id
    await db_session.commit()

    # Reproduce the pre-marker state (the model default leaves NULL anyway,
    # but be explicit so the test survives future default changes).
    await db_session.execute(text("UPDATE courses SET build_completed_at = NULL"))
    await db_session.execute(_BACKFILL)
    await db_session.commit()
    db_session.expire_all()

    rows = {
        cid: (await db_session.get(Course, cid)).build_completed_at
        for cid in (built_id, shell_id, failed_id)
    }
    assert rows[built_id] is not None, "old-heuristic-built course must be stamped"
    assert rows[shell_id] is None, "module-less shell must stay un-stamped (re-buildable)"
    assert rows[failed_id] is None, "build_failed must stay un-stamped"


def test_migration_carries_the_backfill():
    """Source-guard: the backfill statement lives in 0052's upgrade()."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "2026_08_22_0052-0052_course_build_completed_at.py"
    ).read_text()
    assert "UPDATE courses SET build_completed_at = updated_at" in src
    assert "status != 'build_failed'" in src
