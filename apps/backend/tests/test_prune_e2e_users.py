"""prune-e2e-users CLI command — data-hygiene sweep (P3 backlog).

Two halves, mirroring the seed-prod-refusal style:

* env-gating: refuses in production by default, passes in dev, and the
  ``LUMEN_ALLOW_PROD_SEED=1`` override unlocks prod — exercised through the
  shared ``_refuse_prod_seed_or_pass`` guard the command reuses.
* DB-backed: plant 2 e2e-pattern users (one owning a course w/ module +
  lesson) + 1 normal user, run the prune, assert the e2e users AND their
  content are gone while the normal user is untouched; the ``--dry-run`` path
  deletes nothing.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import typer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import _prune_e2e_users, prune_e2e_users
from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
)
from app.models.user import Role, User


def _settings_with_env(env: Environment):
    """Patch only ``Settings.env`` rather than rebuilding via env-vars (which
    would race the conftest cache machinery). Same helper shape as
    ``test_seed_prod_refusal``."""
    s = get_settings()
    return patch.object(s, "env", env)


# --------------------------------------------------------------------------
# env gating — the command reuses the seed-prod-refusal guard, so the
# `prune-e2e-users` command name flows through the exact same mechanism.
# --------------------------------------------------------------------------


def test_refuses_in_production_by_default() -> None:
    """Prod default is REFUSE — a destructive hard-delete sweep must not run
    against prod by accident."""
    with (
        _settings_with_env(Environment.production),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("LUMEN_ALLOW_PROD_SEED", None)
        with pytest.raises(typer.Exit) as exc_info:
            prune_e2e_users(dry_run=True)
        assert exc_info.value.exit_code == 2


def test_explicit_override_allows_prod() -> None:
    """``LUMEN_ALLOW_PROD_SEED=1`` unlocks the prod path (operator opt-in,
    same family as the seed commands). A dry-run keeps it non-destructive."""
    with (
        _settings_with_env(Environment.production),
        patch.dict(os.environ, {"LUMEN_ALLOW_PROD_SEED": "1"}, clear=False),
    ):
        # Should not raise typer.Exit(2). dry-run avoids any DB mutation.
        prune_e2e_users(dry_run=True)


# --------------------------------------------------------------------------
# DB-backed behaviour
# --------------------------------------------------------------------------


async def _seed_fixture(db: AsyncSession) -> dict[str, str]:
    """Plant 2 e2e-pattern users (one owning a course w/ module + lesson) +
    1 normal user. Returns a dict of the ids we assert on later (captured as
    plain strs BEFORE any expire_all — the async-test trap)."""
    subject = Subject(title="Programming", slug="prog-prune-test")
    db.add(subject)
    await db.flush()

    # Two e2e fixture users, matching auth.spec.ts's
    # `e2e-auth-${Date.now()}@lumen.test` template exactly.
    e2e_owner = User(
        email="e2e-auth-1700000000000@lumen.test",
        password_hash=hash_password("x"),
        full_name="E2E Auth User",
        role=Role.user,
    )
    e2e_plain = User(
        email="e2e-auth-1700000000999@lumen.test",
        password_hash=hash_password("x"),
        full_name="E2E Auth User",
        role=Role.user,
    )
    # A normal user that LOOKS adjacent but must NOT be swept: real domain,
    # and an unrelated address.
    normal = User(
        email="real.person@lumen.test",
        password_hash=hash_password("x"),
        full_name="Real Person",
        role=Role.user,
    )
    db.add_all([e2e_owner, e2e_plain, normal])
    await db.flush()

    course = Course(
        owner_id=e2e_owner.id,
        subject_id=subject.id,
        title="E2E Throwaway Course",
        slug="e2e-throwaway-course",
        overview="left behind by a playwright run",
        difficulty=Difficulty.beginner,
        status=CourseStatus.draft,
    )
    db.add(course)
    await db.flush()

    module = Module(course_id=course.id, title="M1", description="", order=0)
    db.add(module)
    await db.flush()

    lesson = Lesson(
        module_id=module.id,
        title="L1",
        type=LessonType.text,
        order=0,
        data={"type": "text", "body_markdown": "hi"},
    )
    db.add(lesson)
    await db.flush()

    ids = {
        "e2e_owner": e2e_owner.id,
        "e2e_plain": e2e_plain.id,
        "normal": normal.id,
        "course": course.id,
        "module": module.id,
        "lesson": lesson.id,
    }
    await db.commit()
    return ids


async def test_prune_removes_e2e_users_and_content(db_session: AsyncSession) -> None:
    """e2e users + their owned course/module/lesson are hard-deleted; the
    normal user survives."""
    ids = await _seed_fixture(db_session)

    # Run the prune logic on the TEST's own session/loop. We call the inner
    # ``_prune_e2e_users(db, ...)`` directly rather than the Typer command:
    # the command wraps the body in ``asyncio.run`` with a fresh engine, which
    # would spin a second event loop and deadlock against the xdist session
    # loop the test fixtures already run on. Passing ``db_session`` keeps the
    # whole DB interaction on one loop — the xdist-safe path.
    await _prune_e2e_users(db_session, dry_run=False)

    # Re-read through our session. expire_all so we re-fetch from the DB
    # rather than the identity map (the deletes above ran in this same
    # session, but expire_all also re-syncs cascade-affected rows).
    db_session.expire_all()

    assert await db_session.get(User, ids["e2e_owner"]) is None
    assert await db_session.get(User, ids["e2e_plain"]) is None
    # Course subtree gone via the explicit course-first delete + CASCADE.
    assert await db_session.get(Course, ids["course"]) is None
    assert await db_session.get(Module, ids["module"]) is None
    assert await db_session.get(Lesson, ids["lesson"]) is None
    # Normal user untouched.
    normal = await db_session.get(User, ids["normal"])
    assert normal is not None
    assert normal.email == "real.person@lumen.test"


async def test_prune_dry_run_deletes_nothing(db_session: AsyncSession) -> None:
    """--dry-run lists but never mutates."""
    ids = await _seed_fixture(db_session)

    await _prune_e2e_users(db_session, dry_run=True)

    db_session.expire_all()

    # Everything still present.
    assert await db_session.get(User, ids["e2e_owner"]) is not None
    assert await db_session.get(User, ids["e2e_plain"]) is not None
    assert await db_session.get(User, ids["normal"]) is not None
    assert await db_session.get(Course, ids["course"]) is not None
    assert await db_session.get(Module, ids["module"]) is not None
    assert await db_session.get(Lesson, ids["lesson"]) is not None


async def test_prune_noop_when_no_e2e_users(db_session: AsyncSession) -> None:
    """No matching rows → clean no-op, normal users untouched."""
    normal = User(
        email="someone@lumen.test",
        password_hash=hash_password("x"),
        full_name="Someone",
        role=Role.user,
    )
    db_session.add(normal)
    await db_session.commit()
    normal_id = normal.id

    await _prune_e2e_users(db_session, dry_run=False)

    db_session.expire_all()
    assert await db_session.get(User, normal_id) is not None
    total = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert total == 1
