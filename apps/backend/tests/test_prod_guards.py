"""H6 — production boot guards.

Each guard has an accept path (returns clean) and a reject path
(raises ``RuntimeError`` with a message that mentions the offending
setting). The guards live in ``app.core.prod_guards`` so they're
unit-testable without the FastAPI app — these tests use a duck-typed
``SimpleNamespace`` so we don't need ``Settings``-level fixtures.

The Settings-level defaults are covered by ``test_config_guard.py``;
this module covers everything H6 layers on top (noop LLM provider,
secret length, loopback DATABASE_URL, OpenAI base URL warning).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.prod_guards import (
    SECRET_MIN_LENGTH,
    _database_host_is_loopback,
    assert_production_safe,
    check_database_not_loopback,
    check_embedding_provider,
    check_llm_base_url_for_openai,
    check_llm_provider,
    check_secret_strength,
    collect_problems,
)


def _prod_settings(**overrides):
    """Return a SimpleNamespace shaped like a production Settings instance.

    Defaults are deliberately *safe* so a test can flip exactly one
    field to red and verify the guard catches that one thing. The
    real Settings's ``is_prod`` property is duck-typed here as a bool.
    """
    base = {
        "is_prod": True,
        "env": SimpleNamespace(value="production"),
        "llm_provider": "anthropic",
        "embedding_provider": "openai",
        "secret_key": "a" * 64,
        "jwt_secret": "b" * 64,
        "database_url": "postgresql+asyncpg://user:pw@db-prod.example.com:5432/lumen",
        "openai_api_base": "https://api.groq.com/openai/v1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- LLM provider ----------


def test_check_llm_provider_rejects_noop_in_prod() -> None:
    s = _prod_settings(llm_provider="noop")
    problems: list[str] = []
    check_llm_provider(s, problems)
    assert any("LLM_PROVIDER=noop" in p for p in problems)


def test_check_llm_provider_accepts_anthropic() -> None:
    s = _prod_settings(llm_provider="anthropic")
    problems: list[str] = []
    check_llm_provider(s, problems)
    assert problems == []


def test_check_llm_provider_accepts_openai() -> None:
    s = _prod_settings(llm_provider="openai")
    problems: list[str] = []
    check_llm_provider(s, problems)
    assert problems == []


def test_check_llm_provider_accepts_enum_value() -> None:
    """``llm_provider`` is a StrEnum in real Settings; coercion must
    survive an enum-looking value too."""
    s = _prod_settings(llm_provider=SimpleNamespace(value="noop"))
    problems: list[str] = []
    check_llm_provider(s, problems)
    assert any("noop" in p for p in problems)


# ---------- Embedding provider ----------


def test_check_embedding_provider_rejects_noop_in_prod() -> None:
    s = _prod_settings(embedding_provider="noop")
    problems: list[str] = []
    check_embedding_provider(s, problems)
    assert any("EMBEDDING_PROVIDER=noop" in p for p in problems)


def test_check_embedding_provider_accepts_openai() -> None:
    s = _prod_settings(embedding_provider="openai")
    problems: list[str] = []
    check_embedding_provider(s, problems)
    assert problems == []


def test_check_embedding_provider_accepts_local() -> None:
    """``local`` means sentence-transformers on box — legitimate in prod."""
    s = _prod_settings(embedding_provider="local")
    problems: list[str] = []
    check_embedding_provider(s, problems)
    assert problems == []


def test_check_embedding_provider_accepts_enum_value() -> None:
    """Match the LLM-provider test — Settings wraps the field in a
    StrEnum-like value and the guard must follow .value coercion."""
    s = _prod_settings(embedding_provider=SimpleNamespace(value="noop"))
    problems: list[str] = []
    check_embedding_provider(s, problems)
    assert any("noop" in p for p in problems)


# ---------- Secret strength ----------


def test_check_secret_strength_rejects_short_secret_key() -> None:
    s = _prod_settings(secret_key="too-short")
    problems: list[str] = []
    check_secret_strength(s, problems)
    assert any("SECRET_KEY" in p for p in problems)


def test_check_secret_strength_rejects_short_jwt_secret() -> None:
    s = _prod_settings(jwt_secret="x" * (SECRET_MIN_LENGTH - 1))
    problems: list[str] = []
    check_secret_strength(s, problems)
    assert any("JWT_SECRET" in p for p in problems)


def test_check_secret_strength_accepts_long_secrets() -> None:
    s = _prod_settings(secret_key="x" * SECRET_MIN_LENGTH, jwt_secret="y" * SECRET_MIN_LENGTH)
    problems: list[str] = []
    check_secret_strength(s, problems)
    assert problems == []


def test_check_secret_strength_handles_secretstr() -> None:
    """Real Settings wraps the value in pydantic's SecretStr; the guard
    must call ``get_secret_value`` rather than ``str(...)``."""

    class _Wrapper:
        def __init__(self, value: str) -> None:
            self._value = value

        def get_secret_value(self) -> str:
            return self._value

    s = _prod_settings(secret_key=_Wrapper("a" * 64), jwt_secret=_Wrapper("b" * 64))
    problems: list[str] = []
    check_secret_strength(s, problems)
    assert problems == []


# ---------- Loopback DATABASE_URL ----------


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://lumen:lumen@localhost:5432/lumen",
        "postgresql+asyncpg://lumen:lumen@127.0.0.1:5432/lumen",
        "postgresql+asyncpg://lumen:lumen@::1:5432/lumen",
        "postgresql+asyncpg://lumen:lumen@0.0.0.0:5432/lumen",
    ],
)
def test_check_database_rejects_loopback(url: str) -> None:
    s = _prod_settings(database_url=url)
    problems: list[str] = []
    check_database_not_loopback(s, problems)
    assert len(problems) == 1
    assert "DATABASE_URL" in problems[0]


def test_check_database_accepts_real_host() -> None:
    s = _prod_settings(
        database_url="postgresql+asyncpg://user:pw@db.prod.example.com:5432/lumen"
    )
    problems: list[str] = []
    check_database_not_loopback(s, problems)
    assert problems == []


def test_check_database_tolerates_password_containing_localhost() -> None:
    """A stray ``localhost`` substring in the password must not trip the
    loopback check — only the host segment matters."""
    s = _prod_settings(
        database_url="postgresql+asyncpg://lumen:plocalhostpw@db.prod.example.com/lumen"
    )
    problems: list[str] = []
    check_database_not_loopback(s, problems)
    assert problems == []


def test_database_host_is_loopback_helper() -> None:
    assert _database_host_is_loopback("postgresql://u:p@localhost/db") is True
    assert _database_host_is_loopback("postgresql://u:p@db.example.com/db") is False
    assert _database_host_is_loopback("") is False


# ---------- OpenAI base URL warning ----------


def test_openai_base_warning_when_unset() -> None:
    s = _prod_settings(llm_provider="openai", openai_api_base="")
    warnings: list[str] = []
    check_llm_base_url_for_openai(s, warnings)
    assert len(warnings) == 1
    assert "Groq" in warnings[0]


def test_openai_base_warning_when_default() -> None:
    s = _prod_settings(llm_provider="openai", openai_api_base="https://api.openai.com/v1")
    warnings: list[str] = []
    check_llm_base_url_for_openai(s, warnings)
    # Operator might *want* real OpenAI — the warning surfaces but
    # doesn't block. We still flag it so the public demo deploy
    # (Groq via OpenAI-compat) doesn't silently bill.
    assert len(warnings) == 1


def test_openai_base_no_warning_for_groq() -> None:
    s = _prod_settings(llm_provider="openai", openai_api_base="https://api.groq.com/openai/v1")
    warnings: list[str] = []
    check_llm_base_url_for_openai(s, warnings)
    assert warnings == []


def test_openai_base_no_warning_when_provider_is_anthropic() -> None:
    s = _prod_settings(llm_provider="anthropic", openai_api_base="")
    warnings: list[str] = []
    check_llm_base_url_for_openai(s, warnings)
    assert warnings == []


# ---------- Aggregate helpers ----------


def test_collect_problems_outside_production_is_noop() -> None:
    s = _prod_settings(is_prod=False, env=SimpleNamespace(value="development"), llm_provider="noop")
    hard, soft = collect_problems(s)
    assert hard == [] and soft == []


def test_collect_problems_lists_every_failure() -> None:
    """One pass through every check returns the full set of problems —
    operators should see the whole list at once, not fix-and-retry."""
    s = _prod_settings(
        llm_provider="noop",
        embedding_provider="noop",
        secret_key="short",
        jwt_secret="short",
        database_url="postgresql+asyncpg://u:p@127.0.0.1/db",
        openai_api_base="",  # also produces a soft warning
    )
    # ``llm_provider=noop`` short-circuits the openai-base warning
    # path (warning is only emitted for ``openai``), so flip provider
    # to ``openai`` and rely on the other reds for the hard problems.
    s.llm_provider = "openai"
    hard, soft = collect_problems(s)
    assert any("EMBEDDING_PROVIDER=noop" in p for p in hard)
    assert any("SECRET_KEY" in p for p in hard)
    assert any("JWT_SECRET" in p for p in hard)
    assert any("DATABASE_URL" in p for p in hard)
    assert any("Groq" in w for w in soft)


def test_assert_production_safe_raises_on_hard_problems() -> None:
    s = _prod_settings(llm_provider="noop")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER=noop"):
        assert_production_safe(s)


def test_assert_production_safe_returns_warnings_on_clean_prod() -> None:
    s = _prod_settings(llm_provider="openai", openai_api_base="")
    warnings = assert_production_safe(s)
    assert any("Groq" in w for w in warnings)


def test_assert_production_safe_returns_empty_outside_prod() -> None:
    s = _prod_settings(is_prod=False, env=SimpleNamespace(value="test"), llm_provider="noop")
    # Should not raise even though llm_provider is noop — guard is prod-only.
    assert assert_production_safe(s) == []
