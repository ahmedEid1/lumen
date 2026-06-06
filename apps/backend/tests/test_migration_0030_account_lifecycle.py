"""S7pre.8 — Migration 0030 account_lifecycle_users_deleted_at.

STRUCTURAL tests only (Gate-B honesty fix): revision identity, chain link,
phase annotation, and the presence of the concurrent-index + idempotent
backfill SQL — all pure-unit, no DB.

The migration's RUNTIME behavior (up/down/up, CONCURRENTLY index build,
legacy-tombstone backfill + idempotency) has been verified MANUALLY twice
against a real Postgres (build-agent scratch harness + Gate-B live
apply/revert) but has **no automated DB-backed regression here yet**. The
shared alembic-runner test harness lands with S1.10
(``test_migration_role_collapse.py`` needs it for 0031/0032) and MUST
retrofit DB-backed coverage for 0030 at that point. Do not claim DB-backed
coverage from this file until then.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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
def mig0030():
    return _load_migration("0030")


def test_revision_identity_and_chain(mig0030):
    assert mig0030.revision == "0030"
    assert mig0030.down_revision == "0029"


def test_has_upgrade_and_downgrade(mig0030):
    assert callable(mig0030.upgrade)
    assert callable(mig0030.downgrade)


def test_concurrent_index_and_backfill_present(mig0030):
    """The migration source must build the index CONCURRENTLY (autocommit
    block) and run the legacy backfill keyed on the reserved tombstone
    email pattern."""
    src = _MIG_DIR.glob("*0030*.py").__next__().read_text()
    assert "autocommit_block" in src, "CONCURRENTLY index needs an autocommit block"
    assert "CONCURRENTLY" in src or "postgresql_concurrently" in src
    assert "ix_users_deleted_at" in src
    assert "deleted-%@lumen.invalid" in src, "legacy backfill must key on the tombstone pattern"
    assert "deleted_at IS NOT NULL" in src or "deleted_at is not null" in src.lower()


def test_phase_annotation_present(mig0030):
    """DR-12: migrations ≥0030 declare their rollout phase. 0030 is Phase A
    (additive)."""
    src = _MIG_DIR.glob("*0030*.py").__next__().read_text()
    assert "Phase A" in src or "phase: A" in src.lower() or 'PHASE = "A"' in src


def test_user_model_has_deleted_at():
    from app.models.user import User

    assert "deleted_at" in User.__mapper__.columns
    col = User.__mapper__.columns["deleted_at"]
    assert col.nullable is True
