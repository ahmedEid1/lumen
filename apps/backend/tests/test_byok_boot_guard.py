"""S7pre.6 — KEK boot guard (ADR-0027 §3, DR-7, R-S3).

``assert_byok_kek_present(settings)`` is called from ``assert_production_safe``
AND fires unconditionally when any ``user_llm_credentials`` OR
``learning_briefs`` row exists (those tables don't exist yet — the guard
reads them defensively, catching ProgrammingError/UndefinedTable). Both API
and worker refuse to boot in prod without a real KEK once credentials exist.

These tests drive the guard logic with duck-typed settings; they do not
require those tables to exist (the table-read is guarded).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import prod_guards


def _settings(*, env="production", keys=None, version=1, secret_key="x" * 48):
    return SimpleNamespace(
        env=SimpleNamespace(value=env),
        is_prod=(env == "production"),
        byok_master_keys=keys or {},
        byok_master_key_version=version,
        secret_key=SimpleNamespace(get_secret_value=lambda: secret_key),
    )


def test_guard_passes_with_real_kek_in_prod():
    import base64
    import os

    keys = {1: SimpleNamespace(get_secret_value=lambda: base64.b64encode(os.urandom(32)).decode())}
    problems: list[str] = []
    prod_guards.assert_byok_kek_present(_settings(keys=keys), problems)
    assert problems == []


def test_guard_rejects_wrong_length_kek_in_prod():
    """Regression (Codex Gate-A): a KEK that is not EXACTLY 32 bytes (AES-256)
    must be flagged. A naive ``>= 32`` check would pass a 33+ byte key through
    the boot guard, then it would blow up at the first ``secrets_crypto`` call
    (``_decode_kek`` requires ``_KEK_LEN == 32``). The guard must prove the KEK
    is usable by the load-bearing primitive, not merely "long enough"."""
    import base64
    import os

    for n in (31, 33, 64):
        keys = {
            1: SimpleNamespace(
                get_secret_value=lambda n=n: base64.b64encode(os.urandom(n)).decode()
            )
        }
        problems: list[str] = []
        prod_guards.assert_byok_kek_present(_settings(keys=keys), problems)
        assert problems, f"{n}-byte KEK must be flagged — only exactly 32 bytes is valid"


def test_guard_flags_missing_kek_in_prod():
    problems: list[str] = []
    prod_guards.assert_byok_kek_present(_settings(keys={}), problems)
    assert problems, "production with no KEK must be flagged"
    assert any("kek" in p.lower() or "byok" in p.lower() for p in problems)


def test_guard_silent_in_dev_without_credentials(monkeypatch):
    """Non-prod with no KEK and no credential/brief rows → no problem."""
    problems: list[str] = []
    # Force the table-existence probe to report no rows.
    monkeypatch.setattr(prod_guards, "_byok_secret_rows_exist", lambda: False)
    prod_guards.assert_byok_kek_present(_settings(env="development", keys={}), problems)
    assert problems == []


def test_guard_fires_in_dev_when_credentials_exist(monkeypatch):
    """Even in dev, a missing KEK with existing credential rows is a problem
    (R-S3 — encrypted material implies a real KEK)."""
    problems: list[str] = []
    monkeypatch.setattr(prod_guards, "_byok_secret_rows_exist", lambda: True)
    prod_guards.assert_byok_kek_present(_settings(env="development", keys={}), problems)
    assert problems, "missing KEK with existing secret rows must be flagged in any env"


def test_secret_rows_probe_tolerates_missing_tables(monkeypatch):
    """The table-read probe must not raise when the tables don't exist —
    it returns False (no rows) instead of propagating ProgrammingError.

    Hermetic since the S5 confirm round: the probe builds its own sync
    engine from ``settings.database_url_sync`` (which conftest does NOT
    repoint at the transient test DB), so the original unpinned version
    silently read the shared dev database and started flapping the moment
    a real credential row landed there (Gate-C stored one). Point it at
    the server's default ``postgres`` database instead — guaranteed to
    have no lumen tables, which is the exact contract under test."""
    from sqlalchemy.engine import make_url

    from app.core.config import get_settings

    s = get_settings()
    bare = make_url(s.database_url_sync).set(database="postgres")
    monkeypatch.setattr(s, "database_url_sync", str(bare))
    result = prod_guards._byok_secret_rows_exist()
    assert result is False


def test_assert_production_safe_includes_kek_guard(monkeypatch):
    """assert_production_safe wires the KEK guard into the prod problem set."""
    monkeypatch.setattr(prod_guards, "_byok_secret_rows_exist", lambda: False)
    s = _settings(env="production", keys={})
    # Make the other prod guards pass so we isolate the KEK failure.
    s.llm_provider = "anthropic"
    s.embedding_provider = "local"
    s.jwt_secret = SimpleNamespace(get_secret_value=lambda: "y" * 48)
    s.database_url = "postgresql+asyncpg://u:p@db-prod.example.com:5432/lumen"
    s.openai_api_base = "https://api.groq.com/openai/v1"
    with pytest.raises(RuntimeError) as exc:
        prod_guards.assert_production_safe(s)
    assert "kek" in str(exc.value).lower() or "byok" in str(exc.value).lower()


def test_worker_process_init_handler_registered():
    """The Celery worker has a worker_process_init handler that runs the guard
    + installs value redaction."""
    from app.workers import celery_app as ca

    assert hasattr(ca, "_on_worker_process_init")
    # Smoke: invoking it in test env (with a derived dev KEK + no secret
    # rows) must not raise.
    ca._on_worker_process_init()
