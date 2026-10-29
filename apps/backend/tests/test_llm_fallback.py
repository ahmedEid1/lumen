"""Platform model fallback chain (LLM_FALLBACK_MODELS).

Pure-unit except the two ``call_logged`` ledger tests at the bottom. Vendor
SDKs are never imported: providers are inline stubs and errors are stand-ins
carrying ``status_code`` / ``code`` the way openai/anthropic ``APIStatusError``
does.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.models.llm_call import STATUS_ERROR, STATUS_OK, LLMCall
from app.services import llm as llm_service
from app.services.llm import (
    ChatMessage,
    ChatResponse,
    FallbackProvider,
    OpenAIProvider,
    build_provider_from_spec,
    get_provider,
    is_fallback_eligible,
)
from app.services.llm_call_log import call_logged
from app.services.llm_providers import PROVIDER_REGISTRY

MSGS = [ChatMessage(role="user", content="q")]


class _StatusError(Exception):
    def __init__(self, status: int, code: str | None = None) -> None:
        super().__init__(f"{status} {code or ''}")
        self.status_code = status
        self.code = code


class APITimeoutError(Exception):
    """Same class name as the openai/anthropic SDK timeout."""


class APIConnectionError(Exception):
    """Same class name as the SDK connection error (host-level)."""


class _Stub:
    name = "openai"

    def __init__(self, model: str, *, raises: BaseException | None = None) -> None:
        self._model = model
        self._raises = raises
        self.calls = 0

    async def chat(self, messages, temperature=0.2):  # pragma: no cover - via chat_with_usage
        return (await self.chat_with_usage(messages, temperature)).text

    async def chat_with_usage(self, messages, temperature=0.2) -> ChatResponse:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return ChatResponse(text="ok", prompt_tokens=10, completion_tokens=5, model=self._model)


# ---------- classification ----------


@pytest.mark.parametrize(
    "exc",
    [
        _StatusError(404, "model_not_found"),
        _StatusError(410),
        _StatusError(500),
        _StatusError(502),
        _StatusError(503),
        _StatusError(400, "model_decommissioned"),
        TimeoutError(),
        APITimeoutError(),
    ],
)
def test_model_availability_errors_are_eligible(exc) -> None:
    assert is_fallback_eligible(exc)


@pytest.mark.parametrize(
    "exc",
    [
        _StatusError(400),
        _StatusError(400, "invalid_request_error"),
        _StatusError(401),
        _StatusError(403),
        _StatusError(413),
        _StatusError(422),
        _StatusError(429),
        APIConnectionError(),
        RuntimeError("OpenAI provider selected but OPENAI_API_KEY is unset"),
    ],
)
def test_request_auth_and_rate_errors_are_not_eligible(exc) -> None:
    assert not is_fallback_eligible(exc)


# ---------- FallbackProvider ----------


async def test_404_moves_to_next_model_and_reports_it() -> None:
    primary = _Stub("openai/gpt-oss-120b", raises=_StatusError(404, "model_not_found"))
    fallback = _Stub("openai/gpt-oss-20b")
    response = await FallbackProvider([primary, fallback]).chat_with_usage(MSGS)
    assert response.model == "openai/gpt-oss-20b"
    assert (primary.calls, fallback.calls) == (1, 1)


@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_non_eligible_error_raises_without_trying_next(status) -> None:
    primary = _Stub("a", raises=_StatusError(status))
    fallback = _Stub("b")
    provider = FallbackProvider([primary, fallback])
    with pytest.raises(_StatusError):
        await provider.chat_with_usage(MSGS)
    assert fallback.calls == 0
    assert provider._model == "a"


async def test_whole_chain_down_raises_last_error_and_names_last_model() -> None:
    provider = FallbackProvider(
        [_Stub("a", raises=_StatusError(404)), _Stub("b", raises=_StatusError(503))]
    )
    with pytest.raises(_StatusError) as exc_info:
        await provider.chat_with_usage(MSGS)
    assert exc_info.value.status_code == 503
    assert provider._model == "b"


def test_fallback_repr_lists_models_never_keys() -> None:
    inner = OpenAIProvider(api_key="SENTINEL", model="openai/gpt-oss-120b")
    provider = FallbackProvider([inner])
    assert "SENTINEL" not in repr(provider)
    assert "openai/gpt-oss-120b" in repr(provider)


# ---------- get_provider wiring ----------


def _openai_settings(fallbacks: list[str]):
    from pydantic import SecretStr

    s = get_settings()
    return (
        patch.object(s, "llm_provider", "openai"),
        patch.object(s, "llm_model", "openai/gpt-oss-120b"),
        patch.object(s, "openai_api_key", SecretStr("sk-test")),
        patch.object(s, "openai_api_base", "https://api.groq.com/openai/v1"),
        patch.object(s, "llm_fallback_models", fallbacks),
    )


def test_get_provider_unchanged_without_fallbacks() -> None:
    a, b, c, d, e = _openai_settings([])
    with a, b, c, d, e:
        provider = get_provider()
    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "openai/gpt-oss-120b"
    # LLM_PROVIDER_TIMEOUT_S / LLM_MAX_RETRIES now reach the SDK client; the
    # timeout also leaves room for a full LLM_MAX_TOKENS answer.
    s = get_settings()
    assert provider._timeout == max(
        float(s.llm_provider_timeout_s), 3600.0 * s.llm_max_tokens / 128_000
    )
    assert provider._max_retries == get_settings().llm_max_retries


def test_get_provider_builds_deduplicated_chain() -> None:
    a, b, c, d, e = _openai_settings(
        ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    )
    with a, b, c, d, e:
        provider = get_provider()
    assert isinstance(provider, FallbackProvider)
    assert [p._model for p in provider._providers] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    assert all(p._api_base == "https://api.groq.com/openai/v1" for p in provider._providers)


def test_noop_never_wraps() -> None:
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "noop"),
        patch.object(s, "llm_fallback_models", ["openai/gpt-oss-20b"]),
    ):
        assert isinstance(get_provider(), llm_service.NoopProvider)


def test_byok_provider_is_never_wrapped() -> None:
    """ADR-0027 §4 item 4: the platform chain never applies to a user's key."""
    s = get_settings()
    with patch.object(s, "llm_fallback_models", ["openai/gpt-oss-20b"]):
        provider = build_provider_from_spec(
            PROVIDER_REGISTRY["groq"], api_key="sk-user", model="llama-3.3-70b-versatile"
        )
    assert isinstance(provider, OpenAIProvider)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("openai/gpt-oss-20b", ["openai/gpt-oss-20b"]),
        (" openai/gpt-oss-20b , qwen/qwen3.8-27b ,", ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]),
    ],
)
def test_env_parses_comma_separated(monkeypatch, raw, expected) -> None:
    monkeypatch.setenv("LLM_FALLBACK_MODELS", raw)
    assert Settings().llm_fallback_models == expected


# ---------- ledger (DB-backed) ----------


@pytest.fixture
def _metered(monkeypatch):
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_ledger_records_the_model_that_answered(db_session, _metered) -> None:
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    provider = FallbackProvider(
        [_Stub("openai/gpt-oss-120b", raises=_StatusError(404)), _Stub("openai/gpt-oss-20b")]
    )
    await call_logged(provider, MSGS, user_id=user_id, feature="tutor", session=db_session)
    await db_session.flush()
    rows = (
        (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id)))
        .scalars()
        .all()
    )
    # One logical call → one row (COUNT-based quotas unchanged), labelled
    # with the fallback model that actually served it.
    assert len(rows) == 1
    assert rows[0].status == STATUS_OK
    assert rows[0].model == "openai/gpt-oss-20b"


async def test_ledger_error_row_names_last_attempted_model(db_session, _metered) -> None:
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    provider = FallbackProvider(
        [
            _Stub("openai/gpt-oss-120b", raises=_StatusError(404)),
            _Stub("b", raises=_StatusError(503)),
        ]
    )
    with pytest.raises(_StatusError):
        await call_logged(provider, MSGS, user_id=user_id, feature="tutor", session=db_session)
    await db_session.flush()
    row = (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id))).scalar_one()
    assert row.status == STATUS_ERROR
    assert row.model == "b"
    assert row.error_kind == "_StatusError"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("[]", []), ('["openai/gpt-oss-20b"]', ["openai/gpt-oss-20b"]), (" a , 'b' ", ["a", "b"])],
)
def test_fallback_models_tolerate_json_looking_values(
    monkeypatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("LLM_FALLBACK_MODELS", raw)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert get_settings().llm_fallback_models == expected
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_connect_and_pool_timeouts_are_not_fallback_eligible() -> None:
    from app.services.llm import is_fallback_eligible

    class ConnectTimeout(Exception):
        pass

    class ReadTimeout(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    connect = APITimeoutError()
    connect.__cause__ = ConnectTimeout()
    read = APITimeoutError()
    read.__cause__ = ReadTimeout()
    assert not is_fallback_eligible(connect)
    assert is_fallback_eligible(read)


def test_sync_timeout_leaves_room_for_a_full_answer(monkeypatch) -> None:
    from app.services import llm as llm_mod

    seen: list[float] = []
    monkeypatch.setattr(
        llm_mod, "build_platform_provider", lambda m, **kw: seen.append(kw["timeout"]) or object()
    )
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("LLM_PROVIDER_TIMEOUT_S", "60")
    monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        llm_mod.get_provider()
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    assert seen and seen[0] >= 115.0
