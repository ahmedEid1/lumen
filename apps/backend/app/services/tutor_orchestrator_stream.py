"""Streaming-tutor orchestrator (L21a, L31-followup wires real LLM).

Wraps the existing :mod:`app.services.tutor_orchestrator` to yield
events instead of returning a single response. Kept as a separate
module so the legacy non-streaming flow stays untouched until the
post-flip legacy-POST refactor.

The orchestrator yields events of these shapes (matches the SSE
wire format the L22 frontend renderer consumes):

- ``planner_start`` — `{model, route}` — the planner is choosing
  which sub-agents to fire.
- ``tool_call_start`` — `{tool, args_head}` — a sub-agent is about
  to run.
- ``tool_call_result`` — `{tool, status, latency_ms, summary}`.
- ``synth_chunk`` — `{delta}` — a token / sentence chunk from the
  synthesiser. Multiple of these per turn.
- ``turn_complete`` — `{message_id, cost_usd, first_token_ms,
  total_ms}` — terminal.
- ``turn_failed`` — `{error_code}` — terminal.

L21a shipped this as a noop stub; the L31-followup wires
:mod:`app.services.llm_stream.stream_chat` so the synth-chunk loop
runs against the real LLM (Groq Llama 3.3 / OpenAI / noop based on
``LLM_PROVIDER``). The terminal ``cost_usd`` comes from the
``include_usage`` payload on the final stream chunk — no estimation
drift.

What's STILL noop: the retriever step. The L21a-followup will wire
the real pgvector lookup against ``lesson_chunks`` and attach the
retrieved chunks to the synth-prompt builder. Today the orchestrator
sends just the user question + a basic system prompt — enough to
demo the wire shape end-to-end against a real provider.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import TypedDict

from app.core.logging import get_logger
from app.services.llm import ChatMessage
from app.services.llm_stream import stream_chat

log = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are Lumen, an AI tutor. Answer the learner's question concisely "
    "and only using established programming knowledge. Refuse anything "
    "off-topic from learning programming + adjacent technologies. Cite "
    "specific concept names where possible. Keep responses under 300 words."
)


class StreamEvent(TypedDict):
    """One event emitted to the Redis Streams turn channel."""

    event: str
    data: dict


async def orchestrate_stream(
    *,
    turn_id: str,
    user_id: str,
    user_message: str,
    course_id: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """Yield a stream of events for a tutor turn.

    L31-followup state: the synth step now calls
    ``llm_stream.stream_chat()`` against the active provider. The
    retriever step is still a noop placeholder — pgvector wiring is
    the next follow-up.
    """
    del course_id, turn_id, user_id  # logged outside; reserved for retrieval

    start_ms = time.monotonic()
    first_token_ms: float | None = None

    # 1. Planner starts.
    yield {
        "event": "planner_start",
        "data": {"model": "stream-orchestrator-v1", "route": "synth-only"},
    }
    await asyncio.sleep(0.01)

    # 2. Retriever (still noop pending pgvector wiring). Emitting
    # the event shape so the frontend tool-row UI renders.
    yield {
        "event": "tool_call_start",
        "data": {"tool": "retriever", "args_head": user_message[:60]},
    }
    await asyncio.sleep(0.01)
    yield {
        "event": "tool_call_result",
        "data": {
            "tool": "retriever",
            "status": "ok",
            "latency_ms": 12,
            "summary": "noop — pgvector wiring is the next follow-up",
        },
    }

    # 3. Real synthesiser via the streaming LLM client.
    messages = [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_message or "(empty)"),
    ]
    total_cost_usd = 0.0
    try:
        async for chunk in stream_chat(messages):
            if chunk.done:
                total_cost_usd = float(chunk.usage.get("cost_usd", 0.0) or 0.0)
                break
            if chunk.delta:
                if first_token_ms is None:
                    first_token_ms = (time.monotonic() - start_ms) * 1000
                yield {"event": "synth_chunk", "data": {"delta": chunk.delta}}
    except NotImplementedError as exc:
        # Anthropic-streaming-not-wired-yet → soft fail; orchestrator
        # still emits a turn_complete with the error code so the
        # frontend reducer doesn't hang.
        log.warning("orchestrate_stream_provider_unsupported", error=str(exc))
        yield {
            "event": "turn_failed",
            "data": {"error_code": "tutor.streaming_unsupported_provider"},
        }
        return
    except Exception as exc:
        log.exception("orchestrate_stream_synth_failed")
        yield {
            "event": "turn_failed",
            "data": {"error_code": f"tutor.runtime: {type(exc).__name__}"},
        }
        return

    # 4. Terminal.
    total_ms = (time.monotonic() - start_ms) * 1000
    yield {
        "event": "turn_complete",
        "data": {
            "message_id": None,  # follow-up persists the assistant turn
            "cost_usd": total_cost_usd,
            "first_token_ms": first_token_ms,
            "total_ms": total_ms,
        },
    }
