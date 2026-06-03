"""Gate-C — Migration 0045 moderation_events_timestamp_defaults.

Two layers:

* **Structural (pure-unit, no DB)** — revision identity + chain link (0045 is
  the head, chaining off the reordered 0043 NOT-NULL boundary), phase
  annotation (A — additive ``SET DEFAULT``, no rewrite), and the upgrade /
  downgrade ``SET DEFAULT now()`` / ``DROP DEFAULT`` shape.

* **DB-backed (runs under ``make test.api`` against real Postgres)** — the
  regression that motivated the migration. ``TimestampMixin`` declares
  ``created_at``/``updated_at`` with ``server_default=func.now()`` so the ORM
  sends NO timestamp values on INSERT; 0033 created ``moderation_events`` with
  both columns NOT NULL but NO server default, so every MIGRATION-built DB
  500s with a NotNullViolation on the first ``POST /share``. The conftest builds
  the test schema from ``Base.metadata.create_all`` (which *does* materialise
  the mixin default), so to reproduce the migration-built gap this layer first
  DROPs the defaults, asserts a timestamp-omitting INSERT then FAILS, runs the
  migration's own ``upgrade()`` SQL, asserts the same INSERT now SUCCEEDS via
  the restored defaults, then restores the schema in a ``finally``.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

_MIG_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(stem: str):
    path = next(_MIG_DIR.glob(f"*{stem}*.py"))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _src(stem: str) -> str:
    return next(_MIG_DIR.glob(f"*{stem}*.py")).read_text()


# --------------------------------------------------------------------------
# Structural (pure-unit)
# --------------------------------------------------------------------------


def test_migration_0045_identity_and_phase():
    m = _load("0045")
    assert m.revision == "0045"
    # 0045 chains off the reordered Phase-D boundary 0043, which is now the
    # second-to-last rev (post-reorder chain 0042 -> 0044 -> 0043 -> 0045).
    assert m.down_revision == "0043"
    assert getattr(m, "PHASE", None) == "A"


def test_migration_0045_sets_then_drops_defaults():
    up_src = inspect.getsource(_load("0045").upgrade)
    down_src = inspect.getsource(_load("0045").downgrade)
    # Upgrade installs now() defaults on both timestamp columns.
    assert up_src.count('server_default=sa.text("now()")') == 2
    assert '"created_at"' in up_src
    assert '"updated_at"' in up_src
    # Downgrade removes them (back to the 0033 shape).
    assert down_src.count("server_default=None") == 2


def test_migration_0045_targets_moderation_events():
    src = _src("0045")
    assert "moderation_events" in src
    assert "TimestampMixin" in src  # the docstring names the ORM contract it aligns


# --------------------------------------------------------------------------
# DB-backed regression (runs under make test.api)
# --------------------------------------------------------------------------


async def _seed_course(db: AsyncSession) -> str:
    """A course row to hang a moderation_events FK off."""
    from app.core.ids import new_id
    from app.core.security import hash_password
    from app.models.course import Subject
    from app.models.user import Role, User

    owner = User(
        email=f"owner-{new_id()[:8]}@lumen.test",
        password_hash=hash_password("Password!1234"),
        full_name="Owner",
        role=Role.instructor,
    )
    subject = Subject(title="Mig45 Subject", slug=f"mig45-{new_id()[:8]}")
    db.add_all([owner, subject])
    await db.commit()
    await db.refresh(owner)
    await db.refresh(subject)

    cid = new_id()
    await db.execute(
        text(
            """
            INSERT INTO courses
                (id, owner_id, subject_id, title, slug, overview, learning_outcomes,
                 difficulty, status, is_featured, created_at, updated_at)
            VALUES
                (:id, :owner, :subject, 'Mig45', :slug, '', '[]'::jsonb, 'beginner',
                 'draft', false, now(), now())
            """
        ),
        {"id": cid, "owner": owner.id, "subject": subject.id, "slug": f"m45-{cid[:8]}"},
    )
    await db.commit()
    return cid


async def _drop_defaults(db: AsyncSession) -> None:
    """Reproduce the migration-built (pre-0045) shape: NOT NULL, no default.

    The conftest builds the schema from ``Base.metadata.create_all``, which
    materialises ``TimestampMixin``'s ``server_default=func.now()``. Dropping
    the defaults here recreates exactly what 0033 left on a real migrated DB so
    the regression below can fail the way prod did before 0045.
    """
    await db.execute(text("ALTER TABLE moderation_events ALTER COLUMN created_at DROP DEFAULT"))
    await db.execute(text("ALTER TABLE moderation_events ALTER COLUMN updated_at DROP DEFAULT"))
    await db.commit()


async def _restore_defaults(db: AsyncSession) -> None:
    """Re-install the defaults after the test.

    The conftest engine is session-scoped and only TRUNCATEs rows between tests
    (the schema is built once), so leaking a DROP DEFAULT would break later
    tests in the same session that rely on the ORM-supplied default. Pair every
    ``_drop_defaults`` with this restore in a ``finally``.
    """
    await db.execute(
        text("ALTER TABLE moderation_events ALTER COLUMN created_at SET DEFAULT now()")
    )
    await db.execute(
        text("ALTER TABLE moderation_events ALTER COLUMN updated_at SET DEFAULT now()")
    )
    await db.commit()


async def _insert_event_omitting_timestamps(db: AsyncSession, course_id: str) -> None:
    """The exact ORM-shaped INSERT POST /share makes (no created_at/updated_at)."""
    from app.core.ids import new_id

    await db.execute(
        text(
            "INSERT INTO moderation_events (id, course_id, to_state) "
            "VALUES (:id, :cid, 'pending_review')"
        ),
        {"id": new_id(), "cid": course_id},
    )


@pytest.mark.asyncio
async def test_0045_restores_defaults_so_bare_insert_succeeds(db_session: AsyncSession):
    """Without defaults the timestamp-omitting INSERT 500s (the prod bug);
    after the migration's upgrade() it succeeds via the now() defaults."""
    cid = await _seed_course(db_session)
    await _drop_defaults(db_session)
    try:
        # Pre-migration: the bare INSERT must fail NOT-NULL on created_at.
        with pytest.raises(IntegrityError):
            await _insert_event_omitting_timestamps(db_session, cid)
        await db_session.rollback()

        # Run the migration's own upgrade() SQL against the live bind.
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        m45 = _load("0045")
        conn = await db_session.connection()

        def _apply(sync_conn):
            ctx = MigrationContext.configure(sync_conn)
            with Operations.context(ctx):
                m45.upgrade()

        await conn.run_sync(_apply)
        await db_session.commit()

        # Post-migration: the same bare INSERT now succeeds and the timestamps
        # are populated by the defaults.
        await _insert_event_omitting_timestamps(db_session, cid)
        await db_session.commit()
        row = (
            await db_session.execute(
                text("SELECT created_at, updated_at FROM moderation_events WHERE course_id=:cid"),
                {"cid": cid},
            )
        ).one()
        assert row[0] is not None
        assert row[1] is not None
    finally:
        await _restore_defaults(db_session)


@pytest.mark.asyncio
async def test_moderation_events_have_now_defaults_in_catalog(db_session: AsyncSession):
    """The live (conftest-built) schema carries now() defaults on both
    timestamp columns — the steady-state the migration converges on."""
    rows = (
        await db_session.execute(
            text(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name='moderation_events' "
                "AND column_name IN ('created_at','updated_at')"
            )
        )
    ).all()
    defaults = dict(rows)
    assert "created_at" in defaults and "updated_at" in defaults
    assert defaults["created_at"] is not None and "now()" in defaults["created_at"]
    assert defaults["updated_at"] is not None and "now()" in defaults["updated_at"]
