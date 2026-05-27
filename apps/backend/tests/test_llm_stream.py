"""LLM streaming dispatcher (L31-followup).

The orchestrator depends on ``stream_chat()`` yielding `StreamChunk`s
in the noop path without a real provider. These tests pin that
contract — provider config is monkey-patched per test so each
exercises a known branch.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.services.llm import ChatMessage
from app.services.llm_stream import StreamChunk, stream_chat


@pytest.fixture(autouse=True)
def _pin_noop():
    """Default each test to the noop provider; opt out per-test."""
    s = get_settings()
    with patch.object(s, "llm_provider", "noop"):
        yield


@pytest.mark.asyncio
async def test_noop_stream_emits_chunks_then_terminal() -> None:
    """Noop path: many delta chunks, one terminal `done=True` with
    zero-cost usage payload."""
    messages = [ChatMessage(role="user", content="hi")]
    chunks: list[StreamChunk] = []
    async for chunk in stream_chat(messages):
        chunks.append(chunk)

    assert len(chunks) > 1, "noop should yield multiple chunks"
    assert chunks[-1].done is True
    assert chunks[-1].usage["cost_usd"] == 0.0
    # All non-terminal chunks carry a non-empty delta.
    for c in chunks[:-1]:
        assert c.delta != ""
        assert c.done is False


@pytest.mark.asyncio
async def test_noop_stream_concatenates_to_full_response() -> None:
    """Each chunk's delta accumulates into a recognisable canned
    answer. Recruiters running the demo locally should see a coherent
    reply, not fragmented junk."""
    messages = [ChatMessage(role="user", content="hi")]
    text = ""
    async for chunk in stream_chat(messages):
        text += chunk.delta
    # Canned reply mentions "TypeScript" and "T" (per the canonical
    # demo question shape).
    assert "TypeScript" in text or "T" in text
    assert len(text) > 100


@pytest.mark.asyncio
async def test_anthropic_provider_requires_api_key() -> None:
    """L37 — Anthropic streaming is now wired. Without an
    ANTHROPIC_API_KEY the dispatcher fails fast with a clear
    RuntimeError rather than hanging on an unauthenticated SDK call."""
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "anthropic"),
        patch.object(s, "anthropic_api_key", None),
        pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"),
    ):
        async for _ in stream_chat([ChatMessage(role="user", content="x")]):
            pass


@pytest.mark.asyncio
async def test_anthropic_stream_yields_text_then_terminal_usage() -> None:
    """L37 — happy path with a fake `messages.stream()` context manager.
    The dispatcher should yield each text delta as a chunk, then a
    terminal chunk carrying the usage payload from `get_final_message`.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    s = get_settings()

    # Stand-in for the SDK's stream context manager.
    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        @property
        def text_stream(self):
            async def _gen():
                for token in ["Hello", " ", "world"]:
                    yield token

            return _gen()

        async def get_final_message(self):
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=11, output_tokens=3))

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = MagicMock()
            self.messages.stream = lambda **kw: FakeStream()

    import sys
    import types

    fake_module = types.ModuleType("anthropic")
    fake_module.AsyncAnthropic = FakeAsyncAnthropic  # type: ignore[attr-defined]
    sys.modules["anthropic"] = fake_module

    with (
        patch.object(s, "llm_provider", "anthropic"),
        patch.object(
            s,
            "anthropic_api_key",
            SimpleNamespace(get_secret_value=lambda: "sk-test"),
        ),
    ):
        chunks = []
        async for c in stream_chat([ChatMessage(role="user", content="hi")]):
            chunks.append(c)

    text_chunks = [c.delta for c in chunks if not c.done]
    assert "".join(text_chunks) == "Hello world"
    assert chunks[-1].done is True
    assert chunks[-1].usage["prompt_tokens"] == 11
    assert chunks[-1].usage["completion_tokens"] == 3


@pytest.mark.asyncio
async def test_unknown_provider_raises_value_error() -> None:
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "made-up-provider"),
        pytest.raises(ValueError, match="unknown LLM provider"),
    ):
        async for _ in stream_chat([ChatMessage(role="user", content="x")]):
            pass
