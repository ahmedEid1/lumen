"""S2.10 — courses.quarantined single-source-of-truth (DR-18-R2).

Structural (pure-unit): migration 0044 identity/phase + PR-12 create-new-then-
drop-old index discipline; the Python authorizer suppresses a quarantined
course even for the owner/enrolled.

DB-backed (runs under make test.api): a quarantined course is invisible in
catalog/search/RAG (incl. the owner retrieval branch) and can_view_course is
False even for an enrolled learner (full quarantine, R-C6′); clearing the flag
restores the prior visibility computation; Python and SQL agree.
"""

from __future__ import annotations

import importlib.util
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import CourseStatus, ModerationState, Visibility
from app.services import visibility as vis

_MIG_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _src(stem: str) -> str:
    return next(_MIG_DIR.glob(f"*{stem}*.py")).read_text()


def _load(stem: str):
    path = next(_MIG_DIR.glob(f"*{stem}*.py"))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# --------------------------------------------------------------------------
# Structural
# --------------------------------------------------------------------------


def test_migration_0044_identity_and_phase():
    m = _load("0044")
    assert m.revision == "0044"
    assert m.down_revision in {"0043", "0033"}
    assert getattr(m, "PHASE", None) == "A"


def test_migration_0044_create_new_then_drop_old():
    """PR-12: CREATE new-name CONCURRENTLY, then DROP old CONCURRENTLY."""
    src = _src("0044")
    assert "ix_courses_listed_v2" in src
    assert "CREATE INDEX CONCURRENTLY" in src
    assert "DROP INDEX CONCURRENTLY" in src
    assert "quarantined = false" in src
    # The new index is created before the old is dropped (no no-index window).
    # Locate by the helper-function source so formatting can't reorder it.
    import inspect

    m = _load("0044")
    fn_src = inspect.getsource(m._rebuild_index)
    create_idx = fn_src.index("CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NEW}")
    drop_old_idx = fn_src.index("DROP INDEX CONCURRENTLY IF EXISTS {_OLD}")
    rename_idx = fn_src.index("ALTER INDEX {_NEW} RENAME TO {_OLD}")
    assert create_idx < drop_old_idx < rename_idx


def test_course_model_has_quarantined():
    from app.models.course import Course

    cols = Course.__mapper__.columns
    assert "quarantined" in cols
    assert cols["quarantined"].nullable is False


@dataclass
class _FakeCourse:
    visibility: str = Visibility.public
    status: str = CourseStatus.published
    moderation_state: str = ModerationState.approved
    deleted_at: object | None = None
    quarantined: bool = True
    owner_id: str = "o1"


def test_quarantined_not_publicly_listed():
    assert vis.is_publicly_listed(_FakeCourse(quarantined=True)) is False
    assert vis.is_publicly_listed(_FakeCourse(quarantined=False)) is True


# --------------------------------------------------------------------------
# DB-backed
# --------------------------------------------------------------------------


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


async def _course(db, owner, *, quarantined):
    from app.models.course import Course, Subject

    subject = Subject(title="S", slug=f"s-{uuid.uuid4().hex[:6]}")
    db.add(subject)
    await db.flush()
    c = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"C {uuid.uuid4().hex[:6]}",
        slug=f"c-{uuid.uuid4().hex[:8]}",
        overview="",
        visibility=Visibility.public,
        status=CourseStatus.published,
        moderation_state=ModerationState.approved,
        quarantined=quarantined,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@pytest.mark.asyncio
async def test_quarantined_invisible_in_catalog_sql(db_session: AsyncSession):
    from app.models.course import Course

    owner = await _owner(db_session)
    q = await _course(db_session, owner, quarantined=True)
    ok = await _course(db_session, owner, quarantined=False)
    ids = {
        r[0]
        for r in (
            await db_session.execute(select(Course.id).where(vis.publicly_listed_sql()))
        ).all()
    }
    assert ok.id in ids
    assert q.id not in ids


@pytest.mark.asyncio
async def test_quarantined_invisible_to_owner_retrieval(db_session: AsyncSession):
    """Even the owner retrieval branch excludes a quarantined course."""
    from app.models.course import Course

    owner = await _owner(db_session)
    q = await _course(db_session, owner, quarantined=True)
    ids = {
        r[0]
        for r in (
            await db_session.execute(select(Course.id).where(vis.retrieval_acl_clause(owner.id)))
        ).all()
    }
    assert q.id not in ids


@pytest.mark.asyncio
async def test_quarantined_can_view_false_even_enrolled(db_session: AsyncSession):
    """R-C6′ full quarantine: hidden even from a previously-enrolled learner."""
    from app.models.course import Enrollment

    owner = await _owner(db_session)
    q = await _course(db_session, owner, quarantined=True)
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.user import Role, User

    learner = User(
        email=f"l-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="L",
        role=Role.student,
    )
    db_session.add(learner)
    await db_session.commit()
    await db_session.refresh(learner)
    db_session.add(Enrollment(user_id=learner.id, course_id=q.id))
    await db_session.commit()

    assert await vis.can_view_course(db_session, q, learner) is False
    assert await vis.can_view_course(db_session, q, owner) is False  # even the owner


@pytest.mark.asyncio
async def test_clearing_quarantine_restores_visibility(db_session: AsyncSession):
    owner = await _owner(db_session)
    q = await _course(db_session, owner, quarantined=True)
    assert await vis.can_view_course(db_session, q, None) is False
    q.quarantined = False
    await db_session.commit()
    await db_session.refresh(q)
    assert await vis.can_view_course(db_session, q, None) is True
