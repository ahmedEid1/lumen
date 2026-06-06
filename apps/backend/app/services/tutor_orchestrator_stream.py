"""Streaming-tutor orchestrator (L21a → L32).

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

L21a shipped this as a noop stub; the L31-followup wired real
``stream_chat`` against the active provider. L32 wires real pgvector
retrieval — callers (the Celery task) run the retriever before
invoking the orchestrator and pass the resulting chunks in, so this
module stays a pure async generator with no DB access.

When ``retrieved_chunks`` is set, the orchestrator:
1. Emits real ``tool_call_start`` / ``tool_call_result`` events with
   the actual chunk count + latency.
2. Folds the chunks into the synth system prompt with an explicit
   ``[L:lesson_id]`` citation contract.

When ``retrieved_chunks`` is None (e.g. /demo with no course):
1. Emits a single ``tool_call_result`` noting no course context.
2. Synth runs without grounding.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import TypedDict

from app.core.logging import get_logger
from app.services import byok as byok_service
from app.services.llm import ChatMessage
from app.services.llm_stream import stream_chat
from app.services.tutor_subagents.retriever import RetrieverChunk

log = get_logger(__name__)

_BASE_SYSTEM_PROMPT = (
    "You are Lumen, an AI tutor. Answer the learner's question concisely "
    "and only using established programming knowledge. Refuse anything "
    "off-topic from learning programming + adjacent technologies. Cite "
    "specific concept names where possible. Keep responses under 300 words."
)

# Appended when retrieved_chunks is non-empty. The citation contract
# is "[L:<lesson_id>]" — the frontend renderer (and a future
# citation-extractor for the eval suite) keys off this exact shape.
_GROUNDING_INSTRUCTION = (
    "\n\nYou have been given course-lesson excerpts below. When a fact "
    "in your answer comes from one of these excerpts, cite the lesson "
    "inline using the exact token ``[L:<lesson_id>]`` — no Markdown link "
    "syntax. If the excerpts do not cover the question, say so and "
    "answer from your general programming knowledge without inventing "
    "citations."
)


def _build_synth_messages(
    user_message: str,
    chunks: list[RetrieverChunk] | None,
) -> list[ChatMessage]:
    """Compose the synth-stage prompt.

    Chunks (when present) are stitched into the SYSTEM message — not
    a separate USER turn — because the citation rule is a system-
    level constraint, not user input. Each chunk is rendered with
    its lesson_id + title + text so the model has a stable handle
    for the ``[L:<id>]`` citation token.
    """
    system_text = _BASE_SYSTEM_PROMPT
    if chunks:
        system_text += _GROUNDING_INSTRUCTION + "\n\n--- Lesson excerpts ---\n"
        for c in chunks:
            system_text += f"\n[L:{c.lesson_id}] {c.lesson_title}\n{c.text}\n"
    return [
        ChatMessage(role="system", content=system_text),
        ChatMessage(role="user", content=user_message or "(empty)"),
    ]


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
    retrieved_chunks: list[RetrieverChunk] | None = None,
    retrieval_latency_ms: int | None = None,
    byok_dispatch: dict[str, str] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Yield a stream of events for a tutor turn.

    L32 state: retrieval is done upstream by the Celery task; this
    function emits the appropriate ``tool_call_*`` events based on
    what the task hands in, and folds chunks into the synth prompt.
    """
    del turn_id, user_id  # logged outside; kept in signature for tracing

    start_ms = time.monotonic()
    first_token_ms: float | None = None

    # 1. Planner starts.
    yield {
        "event": "planner_start",
        "data": {
            "model": "stream-orchestrator-v1",
            "route": "retriever+synth" if retrieved_chunks else "synth-only",
        },
    }
    await asyncio.sleep(0.01)

    # 2. Retriever event — real result if chunks present, otherwise
    # an explanatory noop so the UI still shows the tool row.
    yield {
        "event": "tool_call_start",
        "data": {"tool": "retriever", "args_head": user_message[:60]},
    }
    if retrieved_chunks:
        lesson_ids = {c.lesson_id for c in retrieved_chunks}
        yield {
            "event": "tool_call_result",
            "data": {
                "tool": "retriever",
                "status": "ok",
                "latency_ms": retrieval_latency_ms or 0,
                "summary": (
                    f"found {len(retrieved_chunks)} chunk(s) across {len(lesson_ids)} lesson(s)"
                ),
            },
        }
    else:
        yield {
            "event": "tool_call_result",
            "data": {
                "tool": "retriever",
                "status": "ok",
                "latency_ms": retrieval_latency_ms or 0,
                "summary": (
                    "no course context"
                    if course_id is None
                    else "no relevant content in this course"
                ),
            },
        }

    # 3. Real synthesiser via the streaming LLM client.
    messages = _build_synth_messages(user_message, retrieved_chunks)
    total_cost_usd = 0.0
    # S7: carry the provider's reported token usage off the terminal chunk so
    # the worker can persist it on the streamed turn's llm_calls row. Defaults
    # to 0 so a stream that dies before the usage chunk records honest zeros
    # (the provider billed nothing we can observe).
    prompt_tokens = 0
    completion_tokens = 0
    try:
        async for chunk in stream_chat(messages, byok_dispatch=byok_dispatch):
            if chunk.done:
                total_cost_usd = float(chunk.usage.get("cost_usd", 0.0) or 0.0)
                prompt_tokens = int(chunk.usage.get("prompt_tokens", 0) or 0)
                completion_tokens = int(chunk.usage.get("completion_tokens", 0) or 0)
                break
            if chunk.delta:
                if first_token_ms is None:
                    first_token_ms = (time.monotonic() - start_ms) * 1000
                yield {"event": "synth_chunk", "data": {"delta": chunk.delta}}
    except NotImplementedError as exc:
        log.warning("orchestrate_stream_provider_unsupported", error=str(exc))
        # An unsupported-provider sentinel is never an auth-class failure; the
        # worker's soft-failure handler keys off this flag to mirror the
        # raised-path BYOK credential-invalidation choreography (S7).
        yield {
            "event": "turn_failed",
            "data": {
                "error_code": "tutor.streaming_unsupported_provider",
                "auth_failure": False,
            },
        }
        return
    except Exception as exc:
        log.exception("orchestrate_stream_synth_failed")
        # We own the exception OBJECT here, so we classify auth-class (401/403)
        # at the catch site using the SAME predicate the worker's raised-path
        # except block uses (byok.is_auth_error). The worker's soft-failure
        # branch reads ``auth_failure`` to decide whether to mark the BYOK
        # credential invalid — on a soft-yield it can't re-inspect the
        # exception, so the verdict must ride the event (S7, backward-compatible
        # extra key for the SSE consumer).
        yield {
            "event": "turn_failed",
            "data": {
                "error_code": f"tutor.runtime: {type(exc).__name__}",
                "auth_failure": byok_service.is_auth_error(exc),
            },
        }
        return

    # 4. Terminal.
    total_ms = (time.monotonic() - start_ms) * 1000
    yield {
        "event": "turn_complete",
        "data": {
            "message_id": None,
            "cost_usd": total_cost_usd,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "first_token_ms": first_token_ms,
            "total_ms": total_ms,
        },
    }
