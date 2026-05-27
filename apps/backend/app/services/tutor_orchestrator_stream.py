"""Streaming-tutor orchestrator (L21a).

Wraps the existing :mod:`app.services.tutor_orchestrator` to yield
events instead of returning a single response. Kept as a separate
module so the legacy non-streaming flow stays untouched until L21b's
flag-flip + the legacy POST refactor.

The orchestrator yields events of these shapes (matches the SSE
wire format the L22 frontend renderer consumes):

- ``planner_start`` — `{model, route}` — the planner is choosing
  which sub-agents to fire.
- ``tool_call_start`` — `{tool, args_head}` — a sub-agent is about
  to run.
- ``tool_call_result`` — `{tool, status, latency_ms, summary}` —
  result of the previous tool call.
- ``synth_chunk`` — `{delta}` — a token / sentence chunk from the
  synthesiser. Multiple of these per turn.
- ``turn_complete`` — `{message_id, cost_usd, first_token_ms,
  total_ms}` — terminal.
- ``turn_failed`` — `{error_code, message}` — terminal.

L21a ships this as a *thin* generator. The actual sub-agent
dispatch + LLM streaming integration is deferred to L21a-followups
once we wire AsyncOpenAI's ``stream_options={"include_usage": True}``
through the existing provider abstraction. For L21a the noop path
yields a canned sequence so the wire shape can be verified end-to-end
without a real LLM call.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import TypedDict


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

    L21a-shippable shape: the noop path yields a deterministic
    sequence so we can verify the SSE wire format end-to-end. Real
    LLM streaming lands as a follow-up that swaps the synth-chunk
    branch for an actual AsyncOpenAI ``async for chunk in
    client.chat.completions.create(stream=True, ...)`` loop.

    The signature deliberately doesn't take a DB session — the
    orchestrator emits events; the Celery task wrapping it is the
    one writing them to Redis Streams + transitioning the DB row.
    """
    del user_message, course_id  # consumed by future LLM integration
    del user_id, turn_id  # logged outside

    start_ms = time.monotonic()
    first_token_ms: float | None = None

    # 1. Planner starts.
    yield {"event": "planner_start", "data": {"model": "noop", "route": "noop-plan"}}
    await asyncio.sleep(0.01)

    # 2. Single tool call (retriever) for the noop path.
    yield {
        "event": "tool_call_start",
        "data": {"tool": "retriever", "args_head": "noop-retrieval"},
    }
    await asyncio.sleep(0.01)
    yield {
        "event": "tool_call_result",
        "data": {
            "tool": "retriever",
            "status": "ok",
            "latency_ms": 10,
            "summary": "0 chunks (noop)",
        },
    }

    # 3. Synthesiser emits chunks.
    chunks = [
        "This is a placeholder response. ",
        "The streaming orchestrator wire shape is verified. ",
        "Real LLM streaming integration lands as part of the L21a follow-up.",
    ]
    for chunk in chunks:
        if first_token_ms is None:
            first_token_ms = (time.monotonic() - start_ms) * 1000
        yield {"event": "synth_chunk", "data": {"delta": chunk}}
        await asyncio.sleep(0.005)

    # 4. Terminal.
    total_ms = (time.monotonic() - start_ms) * 1000
    yield {
        "event": "turn_complete",
        "data": {
            "message_id": None,  # L21a-followup will write the message row
            "cost_usd": 0.0,
            "first_token_ms": first_token_ms,
            "total_ms": total_ms,
        },
    }
