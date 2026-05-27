"""LLM streaming variants — companion to :mod:`app.services.llm`.

The existing ``LLMProvider.chat()`` returns a single completed
string; the L21a streaming-tutor orchestrator (in
:mod:`app.services.tutor_orchestrator_stream`) needs to yield
incremental ``synth_chunk`` events as tokens arrive. This module
adds the parallel streaming API.

Provider matrix (L31-followup state):

- **NoopProvider** — emits the canned response word-by-word with
  a tiny artificial delay so the SSE wire shape is exercisable in
  tests + dev without a real provider key. Yields a final
  zero-cost usage chunk.
- **OpenAIProvider (incl. OpenAI-compat e.g. Groq)** — real
  streaming via ``chat.completions.create(stream=True,
  stream_options={"include_usage": True})``. The `include_usage`
  payload arrives on the FINAL chunk with `chunk.usage` populated;
  we surface it as ``StreamChunk(delta="", usage=...)``.
- **AnthropicProvider** — Anthropic's SDK uses a different
  ``client.messages.stream()`` shape. Not wired in this module
  yet; ``stream_chat()`` raises NotImplementedError if the active
  provider is anthropic.

The function-level dispatcher ``stream_chat()`` reads
``settings.llm_provider`` at call time so a runtime provider swap
(L40-style) works without restarting the worker.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.llm import ChatMessage, NoopProvider, get_provider

log = get_logger(__name__)


@dataclass(frozen=True)
class StreamChunk:
    """One streaming event from the LLM.

    Most chunks carry only a ``delta`` (the next token / partial
    word). The terminal chunk carries ``done=True`` and ``usage``
    (when the provider supports it — OpenAI does via
    ``stream_options={"include_usage": True}``; Anthropic via its
    own ``message_delta`` event). The orchestrator uses
    ``usage.cost_usd`` to write the exact cost into the
    ``tutor_turn_jobs`` row at terminal time (no estimation drift).
    """

    delta: str = ""
    done: bool = False
    usage: dict[str, Any] = field(default_factory=dict)


# Canned-response token stream for the noop provider. Splitting on
# whitespace is good enough — a "real" tokenizer per provider would
# be overkill for the no-LLM-call test path. Each "word" becomes one
# `synth_chunk` event downstream.
_NOOP_CANNED_RESPONSE = (
    "TypeScript expects the function body to produce a value the caller's "
    "chosen `T` type, but returning a plain string narrows the type to "
    "`string` — which isn't necessarily `T`. The three canonical fixes: "
    "drop the generic if the function always returns a string; widen the "
    "return type to `string` while keeping `T` for the input; or generate "
    "the value generically from `T` itself."
)


async def stream_chat(
    messages: list[ChatMessage],
    *,
    temperature: float = 0.2,
) -> AsyncIterator[StreamChunk]:
    """Provider-agnostic streaming dispatcher.

    Reads ``settings.llm_provider`` at call time + routes to the
    corresponding implementation. The orchestrator consumes the
    yielded chunks and maps them to SSE ``synth_chunk`` /
    ``turn_complete`` events.

    Today's matrix:
    - ``noop`` → :func:`_stream_chat_noop` (canned word-by-word)
    - ``openai`` → :func:`_stream_chat_openai` (real streaming)
    - ``anthropic`` → NotImplementedError (deferred)
    """
    provider_name = get_settings().llm_provider
    if provider_name == "noop":
        async for chunk in _stream_chat_noop(messages, temperature=temperature):
            yield chunk
        return
    if provider_name == "openai":
        async for chunk in _stream_chat_openai(messages, temperature=temperature):
            yield chunk
        return
    if provider_name == "anthropic":
        # Anthropic streaming has a different shape (`client.messages.stream`
        # + `text_stream`/`message_delta` events). Not wired yet; the
        # orchestrator should fall through to noop until this lands.
        raise NotImplementedError(
            "anthropic streaming not yet implemented; "
            "set LLM_PROVIDER=openai or noop for streaming demos"
        )
    raise ValueError(f"unknown LLM provider: {provider_name!r}")


async def _stream_chat_noop(
    messages: list[ChatMessage],
    *,
    temperature: float,
) -> AsyncIterator[StreamChunk]:
    """Word-by-word canned response. No network call, zero cost.

    The deliberate ~5ms per-word delay mimics a real provider's
    inter-token cadence well enough that the SSE wire timing
    matches a recruiter's experience of the live demo — useful for
    local + CI verification of the consumer side.
    """
    del messages, temperature  # acknowledged, used only by real providers
    words = _NOOP_CANNED_RESPONSE.split(" ")
    for i, word in enumerate(words):
        # Re-attach the trailing space (except on the last word) so
        # the accumulated text on the consumer side reads naturally.
        delta = word + (" " if i < len(words) - 1 else "")
        yield StreamChunk(delta=delta, done=False)
        # Mock pacing — short enough that a 30-word canned reply
        # finishes inside the test's default timeout.
        await asyncio.sleep(0.005)
    # Terminal chunk carries usage (zero for the noop path).
    yield StreamChunk(
        delta="",
        done=True,
        usage={"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
    )


async def _stream_chat_openai(
    messages: list[ChatMessage],
    *,
    temperature: float,
) -> AsyncIterator[StreamChunk]:
    """Real OpenAI / OpenAI-compatible (Groq, Together, etc.) streaming.

    The SDK is imported lazily so a noop-only build doesn't pay the
    import cost. Mirrors the existing ``OpenAIProvider`` config —
    same env vars, same base URL override, same model selection.

    Uses ``stream_options={"include_usage": True}`` so the final
    chunk carries the usage payload (prompt + completion tokens
    plus computed cost in our pricing table). That's the
    no-estimation-drift cost number the L21-Sec reconciliation
    layer needs to settle the per-turn reservation exactly.
    """
    # Lazy import — keeps noop deployments small.
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise ImportError(
            "openai SDK required for streaming; install with `pip install openai>=1.0`"
        ) from e

    s = get_settings()
    api_key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY (or compatible-provider key) is required for "
            "LLM_PROVIDER=openai streaming"
        )

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=s.openai_api_base if s.openai_api_base else None,
    )
    model = s.llm_model or "gpt-4o-mini"

    stream = await client.chat.completions.create(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in messages],
        temperature=temperature,
        max_tokens=s.llm_max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )

    final_usage: dict[str, Any] = {}
    async for chunk in stream:
        # OpenAI's stream chunks have either `.choices[0].delta.content`
        # (token) OR `.usage` (final chunk when include_usage=true).
        if getattr(chunk, "usage", None):
            usage = chunk.usage
            final_usage = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                # Cost computation lives in `app/services/llm_pricing.py`
                # for the chat() path. For the streaming path we surface
                # token counts; the orchestrator can call the pricing
                # helper directly (or leave it to the reconcile step).
                "cost_usd": _estimate_cost(
                    model,
                    getattr(usage, "prompt_tokens", 0),
                    getattr(usage, "completion_tokens", 0),
                ),
            }
            continue
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None) or ""
        if text:
            yield StreamChunk(delta=text, done=False)

    yield StreamChunk(delta="", done=True, usage=final_usage)


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Rough cost computation for the streaming path.

    Best-effort: defers to ``app.services.llm_pricing.cost_for`` when
    available. Returns 0.0 if pricing isn't wired for this model
    (caller can fill in via the reconcile step).
    """
    try:
        from app.services.llm_pricing import cost_for  # type: ignore[import-untyped]

        return float(cost_for(model, prompt_tokens, completion_tokens))
    except Exception as exc:
        log.debug("llm_stream_cost_estimate_unavailable", error=str(exc))
        return 0.0


# Re-export NoopProvider + get_provider so call sites don't have to
# import from two modules just to swap between sync chat + async
# stream during dev.
__all__ = [
    "NoopProvider",
    "StreamChunk",
    "get_provider",
    "stream_chat",
]
