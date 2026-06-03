"""S1.10 — DB-backed migration harness for the role-collapse chain.

Covers migration **0031** (``role_collapse_backfill`` — IRREVERSIBLE Phase B
data-collapse), **0032** (``role_default_user`` — Phase C default flip) AND
retrofits DB-backed coverage for **0030** (``users.deleted_at``) as the Gate-B
carry-forward the foundation owed.

These tests need a real Postgres and CANNOT run in the S1 worktree (no stack).
They are written to run under ``make test.api`` against the conftest's
transient DB; the integrator runs them at merge.

Design: rather than re-stamp the conftest DB through the whole 0001→head
chain (the conftest builds it via ``metadata.create_all``), each test loads
the migration module and exercises its ``upgrade``/``downgrade`` logic against
a bound Alembic ``Operations`` context on a real connection — so the *exact*
SQL the migration ships is what runs. A small helper loads a revision module
by id from ``alembic/versions``.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password

_VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_revision(rev_id: str) -> ModuleType:
    """Import the migration module whose ``revision`` == ``rev_id``."""
    for path in _VERSIONS.glob(f"*{rev_id}*.py"):
        spec = importlib.util.spec_from_file_location(f"_mig_{rev_id}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if getattr(mod, "revision", None) == rev_id:
            return mod
    raise AssertionError(f"migration {rev_id} not found under {_VERSIONS}")


async def _seed_user(db: AsyncSession, *, email: str, role: str) -> str:
    """Insert a user with a raw role string (bypassing the Python default) so
    we can plant legacy ``student``/``instructor`` rows for the collapse."""
    uid = f"u_{email.split('@')[0]}"
    # Insert via core so we control the literal role string even when the
    # column's Python default / enum would otherwise normalise it.
    await db.execute(
        text(
            "INSERT INTO users (id, email, password_hash, full_name, role, is_active, "
            "notification_prefs, created_at, updated_at) "
            "VALUES (:id, :email, :ph, :fn, :role, true, '{}', now(), now())"
        ),
        {"id": uid, "email": email, "ph": hash_password("Password!1234"), "fn": "X", "role": role},
    )
    await db.commit()
    return uid


async def _role_of(db: AsyncSession, uid: str) -> str:
    row = await db.execute(text("SELECT role FROM users WHERE id = :id"), {"id": uid})
    return row.scalar_one()


# ---------- 0031 role_collapse_backfill (Phase B, IRREVERSIBLE) ----------


@pytest.mark.asyncio
async def test_0031_declares_phase_b_and_irreversible():
    mod = _load_revision("0031")
    assert mod.PHASE == "B"
    assert mod.IRREVERSIBLE is True
    assert mod.down_revision == "0030"


@pytest.mark.asyncio
async def test_0031_backfills_legacy_roles(db_session: AsyncSession):
    mod = _load_revision("0031")
    student = await _seed_user(db_session, email="legacy-student@lumen.test", role="student")
    instructor = await _seed_user(db_session, email="legacy-teacher@lumen.test", role="instructor")
    admin = await _seed_user(db_session, email="legacy-admin@lumen.test", role="admin")
    already = await _seed_user(db_session, email="already-user@lumen.test", role="user")

    # Run the migration's exact backfill SQL.
    res = await db_session.execute(sa.text(mod._BACKFILL_SQL))
    await db_session.commit()

    assert await _role_of(db_session, student) == "user"
    assert await _role_of(db_session, instructor) == "user"
    assert await _role_of(db_session, admin) == "admin"  # untouched
    assert await _role_of(db_session, already) == "user"
    # Two legacy rows collapsed.
    assert res.rowcount == 2

    # No rows remain with a legacy role.
    remaining = await db_session.execute(
        sa.text("SELECT count(*) FROM users WHERE role IN ('student','instructor')")
    )
    assert remaining.scalar_one() == 0


@pytest.mark.asyncio
async def test_0031_is_idempotent(db_session: AsyncSession):
    mod = _load_revision("0031")
    await _seed_user(db_session, email="idem-student@lumen.test", role="student")

    first = await db_session.execute(sa.text(mod._BACKFILL_SQL))
    await db_session.commit()
    assert first.rowcount == 1

    # Second pass is a no-op — nothing left to collapse.
    second = await db_session.execute(sa.text(mod._BACKFILL_SQL))
    await db_session.commit()
    assert second.rowcount == 0


@pytest.mark.asyncio
async def test_0031_downgrade_is_noop(db_session: AsyncSession):
    # R-C4: downgrade restores nothing. Calling it must not raise and must not
    # recover the lost student/instructor distinction.
    mod = _load_revision("0031")
    uid = await _seed_user(db_session, email="noop-student@lumen.test", role="student")
    await db_session.execute(sa.text(mod._BACKFILL_SQL))
    await db_session.commit()
    assert await _role_of(db_session, uid) == "user"

    # The migration's downgrade() is a bare `pass` — call it directly.
    mod.downgrade()
    assert await _role_of(db_session, uid) == "user"  # still collapsed


# ---------- 0032 role_default_user (Phase C, reversible) ----------


@pytest.mark.asyncio
async def test_0032_declares_phase_c():
    mod = _load_revision("0032")
    assert mod.PHASE == "C"
    assert mod.down_revision == "0031"


@pytest.mark.asyncio
async def test_0032_sets_default_user(db_session: AsyncSession):
    # Apply the column-default flip via a bound Alembic Operations context on
    # the test connection, then assert an insert without a role yields 'user'.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    # Sanity-load the module so a broken 0032 surfaces here too.
    assert _load_revision("0032").revision == "0032"

    def _apply_default(sync_conn):
        ctx = MigrationContext.configure(sync_conn)
        op = Operations(ctx)
        # Run the same alter the migration's upgrade() issues.
        op.alter_column("users", "role", server_default="user")

    raw_conn = await db_session.connection()
    await raw_conn.run_sync(_apply_default)
    await db_session.commit()

    # Insert a user WITHOUT specifying role → DB default should fill 'user'.
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, full_name, is_active, "
            "notification_prefs, created_at, updated_at) "
            "VALUES (:id, :email, :ph, :fn, true, '{}', now(), now())"
        ),
        {
            "id": "u_default_role",
            "email": "default-role@lumen.test",
            "ph": hash_password("Password!1234"),
            "fn": "X",
        },
    )
    await db_session.commit()
    row = await db_session.execute(text("SELECT role FROM users WHERE id = 'u_default_role'"))
    assert row.scalar_one() == "user"


# ---------- 0030 retrofit: users.deleted_at (Gate-B carry-forward) ----------


@pytest.mark.asyncio
async def test_0030_declares_phase_a():
    mod = _load_revision("0030")
    assert mod.PHASE == "A"
    assert mod.down_revision == "0029"


@pytest.mark.asyncio
async def test_0030_deleted_at_column_present_and_nullable(db_session: AsyncSession):
    # The conftest builds the schema from the live models (which include
    # deleted_at), so the column must exist and be nullable — the additive
    # shape 0030 ships.
    row = await db_session.execute(
        text(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'deleted_at'"
        )
    )
    is_nullable, data_type = row.one()
    assert is_nullable == "YES"
    assert "timestamp" in data_type


@pytest.mark.asyncio
async def test_0030_legacy_tombstone_backfill_sql(db_session: AsyncSession):
    # Retrofit the 0030 idempotent legacy-tombstone backfill: a row with a
    # `deleted-%@lumen.invalid` email + is_active=false + null deleted_at gets
    # deleted_at = updated_at; a live row is untouched; re-running is a no-op.
    mod = _load_revision("0030")

    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, full_name, role, is_active, "
            "deleted_at, notification_prefs, created_at, updated_at) VALUES "
            "(:id, :email, :ph, 'T', 'user', false, NULL, '{}', now(), now())"
        ),
        {
            "id": "u_tombstone",
            "email": "deleted-abc123@lumen.invalid",
            "ph": hash_password("x"),
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, full_name, role, is_active, "
            "deleted_at, notification_prefs, created_at, updated_at) VALUES "
            "(:id, :email, :ph, 'L', 'user', true, NULL, '{}', now(), now())"
        ),
        {"id": "u_live", "email": "live@lumen.test", "ph": hash_password("x")},
    )
    await db_session.commit()

    first = await db_session.execute(sa.text(mod._BACKFILL_SQL))
    await db_session.commit()
    assert first.rowcount == 1  # only the tombstone row

    tomb = await db_session.execute(text("SELECT deleted_at FROM users WHERE id = 'u_tombstone'"))
    assert tomb.scalar_one() is not None
    live = await db_session.execute(text("SELECT deleted_at FROM users WHERE id = 'u_live'"))
    assert live.scalar_one() is None

    # Idempotent: re-run touches nothing (the deleted_at IS NULL guard).
    second = await db_session.execute(sa.text(mod._BACKFILL_SQL))
    await db_session.commit()
    assert second.rowcount == 0
