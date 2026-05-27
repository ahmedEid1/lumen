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
async def test_anthropic_provider_raises_not_implemented() -> None:
    """Anthropic streaming is deferred; calling with that provider
    should surface a clear NotImplementedError, not a silent hang."""
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "anthropic"),
        pytest.raises(NotImplementedError, match="anthropic streaming"),
    ):
        async for _ in stream_chat([ChatMessage(role="user", content="x")]):
            pass


@pytest.mark.asyncio
async def test_unknown_provider_raises_value_error() -> None:
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "made-up-provider"),
        pytest.raises(ValueError, match="unknown LLM provider"),
    ):
        async for _ in stream_chat([ChatMessage(role="user", content="x")]):
            pass
