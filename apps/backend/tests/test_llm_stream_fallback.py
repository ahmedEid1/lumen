"""Platform streaming fallback: only before the first content token.

Fake ``openai`` module installed with ``monkeypatch.setitem`` (restored after
the test — unlike the bare ``sys.modules[...] =`` in test_mistral_provider).
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services.llm import ChatMessage
from app.services.llm_stream import stream_chat


class _StatusError(Exception):
    def __init__(self, status: int, code: str | None = None) -> None:
        super().__init__(str(status))
        self.status_code = status
        self.code = code


def _chunk(text: str | None = None, usage=None):
    choices = [] if text is None else [SimpleNamespace(delta=SimpleNamespace(content=text))]
    return SimpleNamespace(usage=usage, choices=choices)


def _install_fake_openai(monkeypatch, script: dict[str, object]) -> list[dict]:
    """``script[model]`` is an exception to raise at create() or a list of
    chunks / exceptions to yield / raise while iterating."""
    calls: list[dict] = []

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None, **client_kwargs) -> None:
            self._client_kwargs = client_kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        async def _create(self, **kwargs):
            calls.append({**kwargs, "_client": self._client_kwargs})
            plan = script[kwargs["model"]]
            if isinstance(plan, BaseException):
                raise plan

            async def _gen():
                for item in plan:  # type: ignore[union-attr]
                    if isinstance(item, BaseException):
                        raise item
                    yield item

            return _gen()

    fake = types.ModuleType("openai")
    fake.AsyncOpenAI = FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake)
    return calls


@pytest.fixture
def _groq_chain():
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "openai"),
        patch.object(s, "llm_model", "openai/gpt-oss-120b"),
        patch.object(s, "openai_api_key", SecretStr("sk-test")),
        patch.object(s, "openai_api_base", "https://api.groq.com/openai/v1"),
        patch.object(s, "llm_fallback_models", ["openai/gpt-oss-20b"]),
    ):
        yield


async def _drain() -> list:
    return [c async for c in stream_chat([ChatMessage(role="user", content="hi")])]


async def test_404_at_create_streams_from_fallback(monkeypatch, _groq_chain) -> None:
    usage = SimpleNamespace(prompt_tokens=7, completion_tokens=2)
    calls = _install_fake_openai(
        monkeypatch,
        {
            "openai/gpt-oss-120b": _StatusError(404, "model_not_found"),
            "openai/gpt-oss-20b": [_chunk("Hel"), _chunk("lo"), _chunk(usage=usage)],
        },
    )
    chunks = await _drain()
    assert [c["model"] for c in calls] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert "".join(c.delta for c in chunks) == "Hello"
    assert chunks[-1].done is True
    assert chunks[-1].usage["model"] == "openai/gpt-oss-20b"
    assert chunks[-1].usage["prompt_tokens"] == 7
    # The per-read timeout is the configured value on every attempt; fail-fast is
    # enforced separately (no retries + a short wait for the first token).
    assert all(c["timeout"] == float(get_settings().llm_provider_timeout_s) for c in calls)
    assert calls[0]["_client"] == {"max_retries": 0}


async def test_error_after_first_token_does_not_fall_back(monkeypatch, _groq_chain) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        {
            "openai/gpt-oss-120b": [_chunk("partial"), _StatusError(503)],
            "openai/gpt-oss-20b": [_chunk("never")],
        },
    )
    seen: list[str] = []
    with pytest.raises(_StatusError):
        async for c in stream_chat([ChatMessage(role="user", content="hi")]):
            seen.append(c.delta)
    assert seen == ["partial"]
    assert [c["model"] for c in calls] == ["openai/gpt-oss-120b"]


async def test_error_before_first_token_mid_stream_falls_back(monkeypatch, _groq_chain) -> None:
    # A reasoning model can open the stream, emit only reasoning (no content
    # deltas reach us), then fail — still safe to replace.
    calls = _install_fake_openai(
        monkeypatch,
        {
            "openai/gpt-oss-120b": [_chunk(None), _StatusError(500)],
            "openai/gpt-oss-20b": [_chunk("ok")],
        },
    )
    chunks = await _drain()
    assert "".join(c.delta for c in chunks) == "ok"
    assert len(calls) == 2


async def test_bad_request_never_falls_back(monkeypatch, _groq_chain) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        {"openai/gpt-oss-120b": _StatusError(400), "openai/gpt-oss-20b": [_chunk("x")]},
    )
    with pytest.raises(_StatusError):
        await _drain()
    assert len(calls) == 1


async def test_byok_dispatch_never_uses_platform_chain(monkeypatch, _groq_chain) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        {"user-model": _StatusError(404), "openai/gpt-oss-20b": [_chunk("x")]},
    )
    dispatch = {
        "transport": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": "sk-user",
        "model": "user-model",
    }
    with pytest.raises(_StatusError):
        async for _ in stream_chat(
            [ChatMessage(role="user", content="hi")], byok_dispatch=dispatch
        ):
            pass
    assert [c["model"] for c in calls] == ["user-model"]


class ReadTimeout(Exception):
    """Stand-in for httpx.ReadTimeout: the openai SDK raises it unwrapped mid-stream."""


class TimeoutException(Exception):
    pass


class _ReadTimeoutFake(ReadTimeout, TimeoutException):
    pass


_ReadTimeoutFake.__name__ = "ReadTimeout"


async def test_mid_stream_read_timeout_before_first_token_falls_back(
    monkeypatch, _groq_chain
) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        {
            "openai/gpt-oss-120b": [_chunk(None), _ReadTimeoutFake("stalled")],
            "openai/gpt-oss-20b": [_chunk("from fallback")],
        },
    )
    chunks = await _drain()
    assert "".join(c.delta for c in chunks) == "from fallback"
    assert [c["model"] for c in calls] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


async def test_entries_with_a_fallback_behind_them_fail_fast(monkeypatch, _groq_chain) -> None:
    calls = _install_fake_openai(
        monkeypatch,
        {
            "openai/gpt-oss-120b": _StatusError(404, "model_not_found"),
            "openai/gpt-oss-20b": [_chunk("ok")],
        },
    )
    await _drain()
    first, last = calls
    assert first["_client"] == {"max_retries": 0}
    assert last["_client"] == {}  # the last model keeps the SDK's retries


async def test_primary_that_stalls_before_its_first_token_falls_back(
    monkeypatch, _groq_chain
) -> None:
    import asyncio

    import app.services.llm_stream as ls

    class _Stall:
        """A chunk iterable that sends a role-only chunk, then hangs."""

        def __aiter__(self):
            async def _gen():
                yield _chunk("")
                await asyncio.sleep(5)
                yield _chunk("too late")

            return _gen()

    monkeypatch.setattr(ls, "_FAIL_FAST_TIMEOUT_S", 0.05)
    calls = _install_fake_openai(
        monkeypatch, {"openai/gpt-oss-120b": [], "openai/gpt-oss-20b": [_chunk("from fallback")]}
    )
    real_create = None

    import sys

    fake = sys.modules["openai"]
    orig_init = fake.AsyncOpenAI.__init__

    def _init(self, **kw):
        orig_init(self, **kw)
        nonlocal real_create
        real_create = self.chat.completions.create

        async def _create(**kwargs):
            if kwargs["model"] == "openai/gpt-oss-120b":
                calls.append(kwargs)
                return _Stall()
            return await real_create(**kwargs)

        self.chat.completions.create = _create

    monkeypatch.setattr(fake.AsyncOpenAI, "__init__", _init)
    chunks = await _drain()
    assert "".join(c.delta for c in chunks) == "from fallback"


async def test_a_pause_after_the_first_token_does_not_fail_the_turn(
    monkeypatch, _groq_chain
) -> None:
    import asyncio
    import sys

    import app.services.llm_stream as ls

    class _SlowButFine:
        def __aiter__(self):
            async def _gen():
                yield _chunk("first ")
                await asyncio.sleep(0.2)  # longer than the fail-fast budget below
                yield _chunk("second")

            return _gen()

    monkeypatch.setattr(ls, "_FAIL_FAST_TIMEOUT_S", 0.05)
    _install_fake_openai(monkeypatch, {"openai/gpt-oss-20b": [_chunk("unused")]})
    fake = sys.modules["openai"]
    orig_init = fake.AsyncOpenAI.__init__

    def _init(self, **kw):
        orig_init(self, **kw)

        async def _create(**kwargs):
            return _SlowButFine()

        self.chat.completions.create = _create

    monkeypatch.setattr(fake.AsyncOpenAI, "__init__", _init)
    chunks = await _drain()
    assert "".join(c.delta for c in chunks) == "first second"
