"""MistralProvider + streaming branch (L41)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.services.llm import ChatMessage, MistralProvider, OpenAIProvider, get_provider
from app.services.llm_stream import stream_chat


def test_mistral_provider_inherits_openai_transport() -> None:
    """MistralProvider IS-A OpenAIProvider — the chat / chat_with_usage
    methods are inherited as-is."""
    p = MistralProvider(api_key="sk-test", model="mistral-small-latest")
    assert isinstance(p, OpenAIProvider)
    assert p.name == "mistral"


def test_get_provider_returns_mistral_when_configured(monkeypatch) -> None:
    """LLM_PROVIDER=mistral resolves to a MistralProvider with the
    Mistral base URL + Mistral key (not the OpenAI one)."""
    from pydantic import SecretStr

    s = get_settings()
    with (
        patch.object(s, "llm_provider", "mistral"),
        patch.object(s, "mistral_api_key", SecretStr("sk-mistral-test")),
        patch.object(s, "mistral_api_base", "https://api.mistral.ai/v1"),
    ):
        p = get_provider()
        assert isinstance(p, MistralProvider)
        assert p._api_base == "https://api.mistral.ai/v1"
        # The key is now SecretStr-wrapped (S5.6); read it via the
        # redaction-aware accessor. Confirm it came from mistral_api_key,
        # not the empty openai_api_key fallback.
        assert p._key_value() == "sk-mistral-test"


@pytest.mark.asyncio
async def test_mistral_stream_requires_api_key() -> None:
    """L41 — `LLM_PROVIDER=mistral` without MISTRAL_API_KEY fails
    fast with a clear RuntimeError, not a silent hang on an
    unauthenticated SDK call."""
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "mistral"),
        patch.object(s, "mistral_api_key", None),
        pytest.raises(RuntimeError, match="MISTRAL_API_KEY"),
    ):
        async for _ in stream_chat([ChatMessage(role="user", content="x")]):
            pass


@pytest.mark.asyncio
async def test_mistral_stream_uses_mistral_base_and_key(monkeypatch) -> None:
    """The Mistral branch in stream_chat dispatches into the shared
    OpenAI-compat core with the MISTRAL base URL + key. We mock the
    SDK to capture the constructor args."""
    from pydantic import SecretStr

    s = get_settings()
    captured: dict = {}

    class FakeStream:
        def __aiter__(self):
            async def _gen():
                # Yield one usage-only chunk (final chunk shape).
                class Usage:
                    prompt_tokens = 5
                    completion_tokens = 2

                class C:
                    usage = Usage()
                    choices: list = []  # noqa: RUF012 — test stub, no mutation risk

                yield C()

            return _gen()

    class FakeAsyncOpenAI:
        def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = type("c", (), {})()
            self.chat.completions = type("cc", (), {})()  # type: ignore[attr-defined]
            self.chat.completions.create = self._create  # type: ignore[attr-defined]

        async def _create(self, **kwargs):
            captured["model"] = kwargs.get("model")
            return FakeStream()

    import sys
    import types

    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = FakeAsyncOpenAI  # type: ignore[attr-defined]
    sys.modules["openai"] = fake_openai

    with (
        patch.object(s, "llm_provider", "mistral"),
        patch.object(s, "mistral_api_key", SecretStr("sk-mistral-real")),
        patch.object(s, "mistral_api_base", "https://api.mistral.ai/v1"),
        patch.object(s, "mistral_model", "mistral-small-latest"),
        patch.object(s, "llm_model", None),
    ):
        chunks = []
        async for c in stream_chat([ChatMessage(role="user", content="hi")]):
            chunks.append(c)

    assert captured["api_key"] == "sk-mistral-real"
    assert captured["base_url"] == "https://api.mistral.ai/v1"
    assert captured["model"] == "mistral-small-latest"
    # One terminal chunk yielded.
    assert chunks[-1].done is True
