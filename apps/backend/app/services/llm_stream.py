"""LLM streaming variants — companion to :mod:`app.services.llm`.

The existing ``LLMProvider.chat()`` returns a single completed
string; the L21a streaming-tutor orchestrator (in
:mod:`app.services.tutor_orchestrator_stream`) needs to yield
incremental ``synth_chunk`` events as tokens arrive. This module
adds the parallel streaming API.

Provider matrix (L37 state — all three real):

- **NoopProvider** — emits the canned response word-by-word with
  a tiny artificial delay so the SSE wire shape is exercisable in
  tests + dev without a real provider key. Yields a final
  zero-cost usage chunk.
- **OpenAIProvider (incl. OpenAI-compat e.g. Groq)** — real
  streaming via ``chat.completions.create(stream=True,
  stream_options={"include_usage": True})``. The `include_usage`
  payload arrives on the FINAL chunk with `chunk.usage` populated;
  we surface it as ``StreamChunk(delta="", usage=...)``.
- **AnthropicProvider (L37)** — real streaming via
  ``client.messages.stream()``. The SDK exposes a ``text_stream``
  async iterator + ``get_final_message()`` for usage tokens. Same
  StreamChunk contract; cost from the shared pricing helper.

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
    byok_dispatch: dict[str, str] | None = None,
) -> AsyncIterator[StreamChunk]:
    """Provider-agnostic streaming dispatcher.

    Reads ``settings.llm_provider`` at call time + routes to the
    corresponding implementation. The orchestrator consumes the
    yielded chunks and maps them to SSE ``synth_chunk`` /
    ``turn_complete`` events.

    S5.12/DR-8: when ``byok_dispatch`` is supplied (the worker resolved a
    BYOK credential for the foreground user — ``{transport, base_url,
    api_key, model}``) the global ``settings.llm_provider`` switch is
    BYPASSED and the request is dispatched to the registry-fixed base with
    the user's already-decrypted key + model. The decrypt happened upstream
    in ``byok.build_provider`` (the only decrypt site); this function only
    receives the per-request dispatch dict.

    Today's platform matrix:
    - ``noop`` → :func:`_stream_chat_noop` (canned word-by-word)
    - ``openai`` → :func:`_stream_chat_openai` (real streaming)
    - ``anthropic`` → :func:`_stream_chat_anthropic` (real streaming, L37)
    """
    if byok_dispatch is not None:
        if byok_dispatch.get("transport") == "anthropic":
            async for chunk in _stream_chat_anthropic_compat(
                messages,
                temperature=temperature,
                api_key=byok_dispatch["api_key"],
                api_base=byok_dispatch["base_url"],
                model=byok_dispatch["model"],
            ):
                yield chunk
            return
        async for chunk in _stream_chat_openai_compat(
            messages,
            temperature=temperature,
            api_key=byok_dispatch["api_key"],
            api_base=byok_dispatch["base_url"],
            model=byok_dispatch["model"],
        ):
            yield chunk
        return

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
        async for chunk in _stream_chat_anthropic(messages, temperature=temperature):
            yield chunk
        return
    if provider_name == "mistral":
        # L41 — Mistral's Chat Completions API is OpenAI-compatible.
        # The OpenAI streaming code path works as-is when pointed at
        # Mistral's base URL with the Mistral key + default model.
        async for chunk in _stream_chat_openai_compat(
            messages,
            temperature=temperature,
            api_key=_mistral_key(),
            api_base=get_settings().mistral_api_base,
            model=get_settings().llm_model or get_settings().mistral_model,
        ):
            yield chunk
        return
    raise ValueError(f"unknown LLM provider: {provider_name!r}")


def _mistral_key() -> str:
    s = get_settings()
    if not s.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY is required for LLM_PROVIDER=mistral streaming")
    return s.mistral_api_key.get_secret_value()


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

    Reads the OpenAI-tier settings (openai_api_key + openai_api_base
    + llm_model) and dispatches into the shared
    `_stream_chat_openai_compat` core.
    """
    s = get_settings()
    api_key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY (or compatible-provider key) is required for "
            "LLM_PROVIDER=openai streaming"
        )
    async for chunk in _stream_chat_openai_compat(
        messages,
        temperature=temperature,
        api_key=api_key,
        api_base=s.openai_api_base if s.openai_api_base else None,
        model=s.llm_model or "gpt-4o-mini",
    ):
        yield chunk


async def _stream_chat_openai_compat(
    messages: list[ChatMessage],
    *,
    temperature: float,
    api_key: str,
    api_base: str | None,
    model: str,
) -> AsyncIterator[StreamChunk]:
    """L41 — shared core for any OpenAI-compatible streaming endpoint.

    The OpenAI Chat Completions wire shape is the lingua franca of
    LLM APIs at this point (Groq, Mistral, Together, Anyscale,
    Cloudflare Workers AI, etc. all speak it). This factored core
    lets callers pass `(api_key, api_base, model)` and reuse the
    streaming + usage-extraction logic without duplicating it per
    provider.

    Uses `stream_options={"include_usage": True}` so the final
    chunk carries the usage payload (prompt + completion tokens
    plus computed cost via the shared pricing table).
    """
    # Lazy import — keeps noop deployments small.
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise ImportError(
            "openai SDK required for streaming; install with `pip install openai>=1.0`"
        ) from e

    s = get_settings()
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=api_base,
    )

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


async def _stream_chat_anthropic(
    messages: list[ChatMessage],
    *,
    temperature: float,
) -> AsyncIterator[StreamChunk]:
    """Real Anthropic streaming via the official SDK.

    Anthropic's Messages API exposes streaming via
    ``client.messages.stream(...)`` which returns a context manager
    yielding events. The SDK exposes a convenience ``text_stream``
    async iterator on the stream object — each item is a string
    delta. The final ``message`` object (read after the iteration
    completes) carries usage tokens for cost reconciliation.

    Layout mirrors :func:`_stream_chat_openai`:
    - Lazy SDK import so noop deploys don't pay the import cost
    - System prompt collapsed to a single top-level ``system`` arg
      (Messages API rejects ``role="system"`` inside messages)
    - Final usage chunk carries ``prompt_tokens`` /
      ``completion_tokens`` / ``cost_usd`` via the shared pricing
      helper for symmetric reconciliation downstream
    """
    s = get_settings()
    api_key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else ""
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for LLM_PROVIDER=anthropic streaming")
    async for chunk in _stream_chat_anthropic_compat(
        messages,
        temperature=temperature,
        api_key=api_key,
        api_base=s.anthropic_api_base or None,
        model=s.llm_model or "claude-3-5-haiku-latest",
    ):
        yield chunk


async def _stream_chat_anthropic_compat(
    messages: list[ChatMessage],
    *,
    temperature: float,
    api_key: str,
    api_base: str | None,
    model: str,
) -> AsyncIterator[StreamChunk]:
    """S5.12 — Anthropic streaming with explicit key/base/model.

    Shared core so both the platform path (``_stream_chat_anthropic``) and
    the BYOK path (``stream_chat(byok_dispatch=...)``) reuse one streamer.
    The base URL is always registry-fixed for BYOK callers (DR-17).
    """
    try:
        from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "anthropic SDK required for streaming; install with `pip install anthropic>=0.18`"
        ) from e

    s = get_settings()
    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if api_base:
        client_kwargs["base_url"] = api_base
    client = AsyncAnthropic(**client_kwargs)

    # Messages API quirk: ``system`` is a top-level kwarg, not a
    # message turn. Concatenate every leading system message into
    # one string (same convention as the sync AnthropicProvider).
    system_parts = [m.content for m in messages if m.role == "system"]
    system = "\n\n".join(system_parts) if system_parts else ""
    turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

    stream_kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": s.llm_max_tokens,
        "temperature": temperature,
        "messages": turns,
    }
    if system:
        stream_kwargs["system"] = system

    async with client.messages.stream(**stream_kwargs) as stream:
        async for text in stream.text_stream:
            if text:
                yield StreamChunk(delta=text, done=False)
        # ``final_message`` blocks until the stream is fully consumed;
        # the context manager has guaranteed completion at this point.
        final = await stream.get_final_message()
        usage = getattr(final, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)

    yield StreamChunk(
        delta="",
        done=True,
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": _estimate_cost(model, prompt_tokens, completion_tokens),
        },
    )


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
