"""L21a streaming orchestrator event-shape coverage."""

from __future__ import annotations

import pytest

from app.services.tutor_orchestrator_stream import orchestrate_stream


@pytest.mark.asyncio
async def test_orchestrate_stream_emits_expected_event_sequence() -> None:
    """L21a-shippable noop path yields a deterministic sequence so the
    SSE wire format can be verified end-to-end. The sequence is what
    the L22 frontend renderer will key off."""
    events: list[str] = []
    async for ev in orchestrate_stream(turn_id="t_test", user_id="u_test", user_message="hi"):
        events.append(ev["event"])

    # Required boundary events.
    assert events[0] == "planner_start"
    assert events[-1] == "turn_complete"

    # At least one tool-call pair and one synth chunk.
    assert "tool_call_start" in events
    assert "tool_call_result" in events
    assert "synth_chunk" in events

    # tool_call_start must precede its tool_call_result.
    start_idx = events.index("tool_call_start")
    result_idx = events.index("tool_call_result")
    assert start_idx < result_idx


@pytest.mark.asyncio
async def test_orchestrate_stream_records_first_token_latency() -> None:
    """The turn_complete event must carry a first_token_ms number for
    the L22 observability tile to render p50/p95."""
    last_event = None
    async for ev in orchestrate_stream(turn_id="t_test_2", user_id="u_test_2", user_message="hi"):
        last_event = ev

    assert last_event is not None
    assert last_event["event"] == "turn_complete"
    assert isinstance(last_event["data"]["first_token_ms"], int | float)
    assert last_event["data"]["first_token_ms"] >= 0
    assert isinstance(last_event["data"]["total_ms"], int | float)
