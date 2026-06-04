"""S4.2 — Migrations 0048 clone_provenance + 0049 idempotency_keys.

Two layers (mirroring ``test_migration_0033_visibility.py``):

* **Structural (pure-unit, no DB)** — revision identity + chain link, phase
  annotation (both Phase A, before the gated 0043 boundary), additive-only
  add_column, the CONCURRENTLY index in an autocommit block, clean downgrades.

* **DB-backed (runs under ``make test.api`` against real Postgres)** — the
  conftest builds the test schema from ``Base.metadata.create_all`` (the model
  already declares the S4.1 columns/table/indexes), so this layer asserts the
  end state the migration produces: the 6 provenance columns + ``enrollments
  .is_self`` (server_default false) + the ``idempotency_keys`` table with
  ``uq_idem_user_key`` + the two clone indexes all exist.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MIG_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(stem_contains: str):
    matches = [p for p in _MIG_DIR.glob("*.py") if stem_contains in p.name]
    assert matches, f"no migration file containing {stem_contains!r}"
    path = matches[0]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def mig0048():
    return _load_migration("0048")


@pytest.fixture(scope="module")
def mig0049():
    return _load_migration("0049")


@pytest.fixture(scope="module")
def src0048() -> str:
    return next(_MIG_DIR.glob("*0048*.py")).read_text()


@pytest.fixture(scope="module")
def src0049() -> str:
    return next(_MIG_DIR.glob("*0049*.py")).read_text()


# --------------------------------------------------------------------------
# Structural (pure-unit)
# --------------------------------------------------------------------------


def test_0048_revision_identity_and_chain(mig0048):
    assert mig0048.revision == "0048"
    # HOUSE RULES: chains off the current last Phase-A revision (0047) so the
    # gated 0043 boundary stays LAST.
    assert mig0048.down_revision == "0047"


def test_0049_revision_identity_and_chain(mig0049):
    assert mig0049.revision == "0049"
    assert mig0049.down_revision == "0048"


def test_both_phase_a(mig0048, mig0049):
    assert getattr(mig0048, "PHASE", None) == "A"
    assert getattr(mig0049, "PHASE", None) == "A"


def test_0048_additive_only(src0048):
    # Six provenance columns, all nullable (additive, instant on PG17).
    for col in (
        "origin_course_id",
        "origin_owner_id",
        "root_origin_course_id",
        "origin_title_snapshot",
        "origin_owner_name_snapshot",
        "cloned_at",
    ):
        assert col in src0048, f"migration 0048 missing column {col}"
    # enrollments.is_self with a server_default so the ADD COLUMN is instant.
    assert "is_self" in src0048
    assert "server_default" in src0048
    # The clone provenance columns are additive — no table rewrite.
    assert "nullable=True" in src0048


def test_0048_concurrent_indexes_in_autocommit_block(src0048):
    assert "autocommit_block" in src0048
    assert "CONCURRENTLY" in src0048
    assert "ix_courses_origin_course_id" in src0048
    assert "ix_courses_root_origin" in src0048
    # Re-runnability: DROP IF EXISTS before the CONCURRENTLY build (0014 GIN
    # pattern) so a failed prior build (INVALID index) is cleaned up.
    assert "IF EXISTS" in src0048


def test_0048_downgrade_drops_cleanly(mig0048):
    import inspect

    down_src = inspect.getsource(mig0048.downgrade)
    assert 'drop_column("courses", "origin_course_id")' in down_src
    assert 'drop_column("enrollments", "is_self")' in down_src
    # The downgrade drops both clone indexes (CONCURRENTLY, via the module
    # constants ``_ORIGIN_IDX``/``_ROOT_IDX``) before the columns.
    assert mig0048._ORIGIN_IDX == "ix_courses_origin_course_id"
    assert mig0048._ROOT_IDX == "ix_courses_root_origin"
    assert "_ORIGIN_IDX" in down_src
    assert "_ROOT_IDX" in down_src
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in down_src


def test_0049_creates_idempotency_table(src0049):
    assert "idempotency_keys" in src0049
    assert "uq_idem_user_key" in src0049
    assert "create_table" in src0049


def test_0049_downgrade_drops_table(mig0049):
    import inspect

    down_src = inspect.getsource(mig0049.downgrade)
    assert "drop_table" in down_src
    assert "idempotency_keys" in down_src


# --------------------------------------------------------------------------
# DB-backed schema (runs under make test.api)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_columns_present(db_session: AsyncSession):
    cols = {
        r[0]
        for r in (
            await db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='courses'"
                )
            )
        ).all()
    }
    for col in (
        "origin_course_id",
        "origin_owner_id",
        "root_origin_course_id",
        "origin_title_snapshot",
        "origin_owner_name_snapshot",
        "cloned_at",
    ):
        assert col in cols, f"courses missing {col}"


@pytest.mark.asyncio
async def test_enrollments_is_self_present_default_false(db_session: AsyncSession):
    row = (
        await db_session.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name='enrollments' AND column_name='is_self'"
            )
        )
    ).one_or_none()
    assert row is not None, "enrollments.is_self missing"
    assert row[1] == "NO"  # NOT NULL
    assert row[2] is not None and "false" in row[2].lower()


@pytest.mark.asyncio
async def test_idempotency_keys_table_present(db_session: AsyncSession):
    exists = (
        await db_session.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name='idempotency_keys'")
        )
    ).scalar_one_or_none()
    assert exists == 1
    # The unique constraint backing the (user, key) lookup.
    uq = (
        await db_session.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_name='idempotency_keys' AND constraint_name='uq_idem_user_key_endpoint'"
            )
        )
    ).scalar_one_or_none()
    assert uq == 1


@pytest.mark.asyncio
async def test_clone_indexes_present(db_session: AsyncSession):
    idx = {
        r[0]
        for r in (
            await db_session.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename='courses'")
            )
        ).all()
    }
    assert "ix_courses_origin_course_id" in idx
    assert "ix_courses_root_origin" in idx
