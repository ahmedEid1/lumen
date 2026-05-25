"""Production boot guards (Phase H6).

These checks complement :meth:`app.core.config.Settings.assert_production_ready`
by catching footguns specific to the public demo deploy: shipping with the
``noop`` LLM provider, secrets shorter than 32 chars (HS256 / RFC 7518 §3.2),
or a stray ``DATABASE_URL`` pointing at a localhost Postgres.

They live in their own module so the assertions can be exercised by unit
tests without spinning up the FastAPI app — the existing ``test_config_guard``
tests Settings-level invariants; ``test_prod_guards`` tests these.

Conventions:

* ``check_production_ready(settings)`` raises ``RuntimeError`` with a
  joined human-readable message listing every problem found, so an
  operator sees the full set in one pass rather than fixing-and-rebooting.
* Soft signals (e.g. ``OPENAI_API_BASE`` unset while ``LLM_PROVIDER=openai``)
  return as a separate list of warnings; the caller logs them but the
  boot proceeds.
"""

from __future__ import annotations

from typing import Any

# A 32-byte (256-bit) minimum mirrors the HS256 floor PyJWT uses for
# `InsecureKeyLengthWarning` and matches the test conftest's fixture key.
# Anything below this is rejected outright — recoverable only by env-var
# rotation, which is the documented secret-rotation procedure.
SECRET_MIN_LENGTH = 32

_LOCALHOST_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")  # noqa: S104  comparison only


def _is_production(settings: Any) -> bool:
    """Detect whether the supplied settings describe a production deployment.

    Works against the real ``Settings`` enum and against minimal duck-typed
    stand-ins used in tests. We check ``is_prod`` first because that's the
    canonical property; falling back to a string compare keeps the helper
    usable from test fixtures that pass a ``SimpleNamespace``.
    """
    is_prod = getattr(settings, "is_prod", None)
    if isinstance(is_prod, bool):
        return is_prod
    env = getattr(settings, "env", None)
    return getattr(env, "value", env) == "production"


def _secret_value(secret: Any) -> str:
    """Pull a plain-text value out of a SecretStr-or-str field.

    The ``Settings`` model wraps sensitive fields in ``SecretStr``; tests
    sometimes pass a bare string. Tolerate both so the guard logic stays
    the same shape.
    """
    if secret is None:
        return ""
    getter = getattr(secret, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(secret)


def _database_host_is_loopback(url: str) -> bool:
    """Best-effort check that a DSN does not point at a loopback host.

    We don't want to import ``sqlalchemy.engine.url`` just for this — the
    DSN shapes we accept are well known and a substring check is enough.
    The check intentionally ignores port/path so a real cloud Postgres
    on, say, ``db-prod.lumen.example.com:5432`` cleanly passes.
    """
    if not url:
        return False
    lower = url.lower()
    # Snip past the ``user:pass@`` if present so we don't false-positive
    # on a stray ``localhost`` in a password.
    if "@" in lower:
        lower = lower.split("@", 1)[1]
    return any(host in lower for host in _LOCALHOST_HOSTS)


def check_llm_provider(settings: Any, problems: list[str]) -> None:
    """Reject the ``noop`` provider in production.

    The noop provider returns deterministic canned text. Shipping with it
    enabled would silently disable the RAG tutor + AI authoring features
    in production — a quiet regression that's hard to spot from logs.
    """
    provider = getattr(settings, "llm_provider", None)
    value = getattr(provider, "value", provider)
    if value == "noop":
        problems.append(
            "LLM_PROVIDER=noop is forbidden in production; "
            "set it to one of: anthropic, openai (with OPENAI_API_BASE for Groq)"
        )


def check_embedding_provider(settings: Any, problems: list[str]) -> None:
    """Reject the ``noop`` embedding provider in production.

    The noop embedder returns deterministic hash-seeded zero-magnitude
    vectors so the stack still boots without a paid embedding key. In
    production that silently breaks RAG: every cosine similarity returns
    the same garbage ranking, so retrieval is functionally disabled with
    no error in the logs. Mirror the LLM guard so the compose comment
    promising this behaviour is actually true.
    """
    provider = getattr(settings, "embedding_provider", None)
    value = getattr(provider, "value", provider)
    if value == "noop":
        problems.append(
            "EMBEDDING_PROVIDER=noop is forbidden in production; "
            "set it to 'openai' (Cloudflare Workers AI or paid OpenAI via "
            "OpenAI-compat) or 'local' (sentence-transformers on box)"
        )


def check_secret_strength(settings: Any, problems: list[str]) -> None:
    """Reject SECRET_KEY (and JWT_SECRET) shorter than 32 chars.

    HS256 with a sub-256-bit key is the most common JWT misconfiguration
    in the wild. PyJWT itself emits ``InsecureKeyLengthWarning`` for the
    same threshold; we promote that to a refusal-to-boot to make sure no
    production deploy ever signs a token with a guessable key.
    """
    secret = _secret_value(getattr(settings, "secret_key", None))
    if len(secret) < SECRET_MIN_LENGTH:
        problems.append(
            f"SECRET_KEY must be at least {SECRET_MIN_LENGTH} characters long"
            " (HS256 / RFC 7518 §3.2 floor); generate via "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'`"
        )
    jwt_secret = _secret_value(getattr(settings, "jwt_secret", None))
    if len(jwt_secret) < SECRET_MIN_LENGTH:
        problems.append(
            f"JWT_SECRET must be at least {SECRET_MIN_LENGTH} characters long"
        )


def check_database_not_loopback(settings: Any, problems: list[str]) -> None:
    """Reject DATABASE_URL pointing at localhost / 127.0.0.1 in prod.

    Catches the staging-misconfig-as-prod case where an operator flipped
    ``ENV=production`` against a forgotten compose-local Postgres URL.
    Supabase / RDS / Crunchy / Neon all return real hostnames, so any
    legitimate prod DSN survives this check cleanly.
    """
    url = getattr(settings, "database_url", "") or ""
    if _database_host_is_loopback(str(url)):
        problems.append(
            "DATABASE_URL points at a loopback host (localhost / 127.0.0.1); "
            "production should use a real managed Postgres (Supabase / RDS / Neon / …)"
        )


def check_llm_base_url_for_openai(settings: Any, warnings: list[str]) -> None:
    """Soft signal: ``LLM_PROVIDER=openai`` without an explicit ``OPENAI_API_BASE``.

    The public demo deploy points the OpenAI provider at Groq's
    OpenAI-compatible endpoint (`https://api.groq.com/openai/v1`) so the
    LLM tier stays free. If the operator selected ``openai`` but left the
    base URL at the real OpenAI default, they're probably about to incur
    dollar costs they didn't plan for. Warn loudly but don't refuse the
    boot — paid OpenAI is a perfectly legitimate config.
    """
    provider = getattr(settings, "llm_provider", None)
    value = getattr(provider, "value", provider)
    if value != "openai":
        return
    base = getattr(settings, "openai_api_base", "") or ""
    if not base or base.strip().rstrip("/") in {"", "https://api.openai.com/v1"}:
        warnings.append(
            "LLM_PROVIDER=openai but OPENAI_API_BASE is unset / pointed at "
            "api.openai.com — if you meant to run on Groq (free tier), set "
            "OPENAI_API_BASE=https://api.groq.com/openai/v1"
        )


def collect_problems(settings: Any) -> tuple[list[str], list[str]]:
    """Run every guard and return ``(hard_problems, soft_warnings)``.

    Outside of production this returns two empty lists — these checks
    only apply when the operator has flipped ``ENV=production`` because
    dev / test / staging legitimately run against loopback hosts, the
    noop LLM provider, and short fixture secrets.
    """
    if not _is_production(settings):
        return [], []
    problems: list[str] = []
    warnings: list[str] = []
    check_llm_provider(settings, problems)
    check_embedding_provider(settings, problems)
    check_secret_strength(settings, problems)
    check_database_not_loopback(settings, problems)
    check_llm_base_url_for_openai(settings, warnings)
    return problems, warnings


def assert_production_safe(settings: Any) -> list[str]:
    """Raise ``RuntimeError`` if any hard guard fails; return soft warnings.

    Designed to be called from the FastAPI lifespan hook *after*
    :meth:`Settings.assert_production_ready`. Returning the warning list
    lets the caller route the warnings through ``structlog`` without
    this module needing to import the logger.
    """
    problems, warnings = collect_problems(settings)
    if problems:
        raise RuntimeError(
            "Production boot guard refused to start: "
            + "; ".join(problems)
            + ". Fix your environment and try again."
        )
    return warnings
