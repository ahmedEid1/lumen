"""L21a streaming orchestrator event-shape coverage (+ L32 grounding)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.services.tutor_orchestrator_stream import orchestrate_stream
from app.services.tutor_subagents.retriever import RetrieverChunk


@pytest.fixture(autouse=True)
def _pin_noop_llm_provider():
    """L31-followup: orchestrate_stream now dispatches through
    `llm_stream.stream_chat()` which routes by `settings.llm_provider`.
    CI's test env defaults to anthropic; pin noop so the orchestrator
    runs end-to-end without a real provider key (and without hitting
    the anthropic-not-implemented branch that emits turn_failed)."""
    s = get_settings()
    with patch.object(s, "llm_provider", "noop"):
        yield


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


# ---------------------------------------------------------------------
# L32 — pgvector grounding coverage
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_chunks_no_course_id_summary_reads_no_course_context() -> None:
    """Demo route (no course context): the retriever's tool_call_result
    should explain WHY there's no grounding — so the UI's reasoning
    panel doesn't show a blank '0 chunks' tile that looks broken."""
    summaries: list[str] = []
    async for ev in orchestrate_stream(
        turn_id="t_demo",
        user_id="u_demo",
        user_message="What is a closure?",
        course_id=None,
        retrieved_chunks=None,
    ):
        if ev["event"] == "tool_call_result":
            summaries.append(ev["data"]["summary"])

    assert any("no course context" in s for s in summaries)


@pytest.mark.asyncio
async def test_no_chunks_with_course_id_summary_reads_no_relevant() -> None:
    """Course route but retrieval came back empty: the summary should
    distinguish 'we tried and found nothing' from 'we never tried'."""
    summaries: list[str] = []
    async for ev in orchestrate_stream(
        turn_id="t_empty",
        user_id="u_empty",
        user_message="esoteric topic",
        course_id="c_some_real_course",
        retrieved_chunks=None,
    ):
        if ev["event"] == "tool_call_result":
            summaries.append(ev["data"]["summary"])

    assert any("no relevant content" in s for s in summaries)


@pytest.mark.asyncio
async def test_with_chunks_emits_real_summary_and_latency() -> None:
    """When chunks ARE handed in, the tool_call_result summary should
    show the real counts + latency the Celery task measured."""
    chunks = [
        RetrieverChunk(
            lesson_id="l_alpha",
            lesson_title="Closures",
            text="A closure is a function bundled with its lexical environment.",
            score=0.05,
        ),
        RetrieverChunk(
            lesson_id="l_alpha",  # same lesson, different chunk → still 1 lesson
            lesson_title="Closures",
            text="Closures capture variables by reference.",
            score=0.10,
        ),
        RetrieverChunk(
            lesson_id="l_beta",
            lesson_title="Scoping",
            text="Block scoping rules differ across languages.",
            score=0.20,
        ),
    ]
    summaries: list[str] = []
    latencies: list[int] = []
    routes: list[str] = []
    async for ev in orchestrate_stream(
        turn_id="t_grounded",
        user_id="u_grounded",
        user_message="What is a closure?",
        course_id="c_js_basics",
        retrieved_chunks=chunks,
        retrieval_latency_ms=42,
    ):
        if ev["event"] == "tool_call_result":
            summaries.append(ev["data"]["summary"])
            latencies.append(ev["data"]["latency_ms"])
        if ev["event"] == "planner_start":
            routes.append(ev["data"]["route"])

    # 3 chunks across 2 distinct lessons.
    assert any("3 chunk" in s and "2 lesson" in s for s in summaries)
    assert 42 in latencies
    # Route advertised to the UI flips from 'synth-only' → 'retriever+synth'.
    assert routes == ["retriever+synth"]


@pytest.mark.asyncio
async def test_with_chunks_synth_prompt_carries_citation_contract() -> None:
    """When chunks are present the synth-stage SYSTEM message must
    include the [L:<lesson_id>] citation contract + the lesson
    excerpts. Without this the model has no anchor for the citation
    tokens and the eval suite's citation-extractor finds nothing."""
    chunks = [
        RetrieverChunk(
            lesson_id="l_z9",
            lesson_title="Hoisting",
            text="`var` declarations are hoisted to the top of their scope.",
            score=0.07,
        ),
    ]

    # Capture the messages handed to stream_chat. We mock it to a
    # no-yield async generator so the orchestrator finishes cleanly
    # after recording the call.
    captured: dict = {}

    async def _fake_stream_chat(messages, byok_dispatch=None):  # S5: new kwarg
        captured["messages"] = messages
        # Emit one synth chunk + a terminal so the orchestrator's
        # post-loop "turn_complete" branch fires.
        from app.services.llm_stream import StreamChunk

        yield StreamChunk(delta="ok", done=False, usage={})
        yield StreamChunk(delta="", done=True, usage={"cost_usd": 0.0})

    with patch(
        "app.services.tutor_orchestrator_stream.stream_chat",
        _fake_stream_chat,
    ):
        async for _ in orchestrate_stream(
            turn_id="t_cite",
            user_id="u_cite",
            user_message="What's hoisting?",
            course_id="c_js",
            retrieved_chunks=chunks,
            retrieval_latency_ms=10,
        ):
            pass

    msgs = captured["messages"]
    assert msgs[0].role == "system"
    system_text = msgs[0].content
    assert "[L:<lesson_id>]" in system_text  # the literal citation contract token
    assert "[L:l_z9]" in system_text  # the actual lesson handle
    assert "Hoisting" in system_text
    assert "var" in system_text  # the excerpt body
    # The USER turn is the verbatim question, not the system-stitched bundle.
    assert msgs[1].role == "user"
    assert msgs[1].content == "What's hoisting?"


# ---------------------------------------------------------------------
# S7 — token usage from the terminal stream chunk lands on turn_complete
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_complete_carries_provider_token_usage() -> None:
    """S7: when the provider's terminal chunk reports prompt/completion
    tokens, orchestrate_stream surfaces them on the turn_complete event so
    the worker can persist them on the streamed turn's llm_calls row."""

    async def _fake_stream_chat(messages, byok_dispatch=None):
        del messages, byok_dispatch
        from app.services.llm_stream import StreamChunk

        yield StreamChunk(delta="answer", done=False)
        yield StreamChunk(
            delta="",
            done=True,
            usage={"prompt_tokens": 137, "completion_tokens": 42, "cost_usd": 0.0009},
        )

    with patch(
        "app.services.tutor_orchestrator_stream.stream_chat",
        _fake_stream_chat,
    ):
        last = None
        async for ev in orchestrate_stream(
            turn_id="t_usage",
            user_id="u_usage",
            user_message="hi",
            course_id=None,
            retrieved_chunks=None,
        ):
            last = ev

    assert last is not None
    assert last["event"] == "turn_complete"
    assert last["data"]["prompt_tokens"] == 137
    assert last["data"]["completion_tokens"] == 42
    assert last["data"]["cost_usd"] == pytest.approx(0.0009)


@pytest.mark.asyncio
async def test_turn_complete_tokens_zero_when_no_usage_chunk() -> None:
    """S7: a terminal chunk that omits token counts (older provider /
    partial usage payload) yields honest zeros — we claim only what the
    provider actually reported."""

    async def _fake_stream_chat(messages, byok_dispatch=None):
        del messages, byok_dispatch
        from app.services.llm_stream import StreamChunk

        yield StreamChunk(delta="answer", done=False)
        # done chunk with no token fields (only cost).
        yield StreamChunk(delta="", done=True, usage={"cost_usd": 0.0})

    with patch(
        "app.services.tutor_orchestrator_stream.stream_chat",
        _fake_stream_chat,
    ):
        last = None
        async for ev in orchestrate_stream(
            turn_id="t_nousage",
            user_id="u_nousage",
            user_message="hi",
            course_id=None,
            retrieved_chunks=None,
        ):
            last = ev

    assert last is not None
    assert last["event"] == "turn_complete"
    assert last["data"]["prompt_tokens"] == 0
    assert last["data"]["completion_tokens"] == 0


@pytest.mark.asyncio
async def test_stream_dies_before_usage_chunk_emits_turn_failed_not_complete() -> None:
    """S7: a stream that raises before the terminal usage chunk arrives
    produces a turn_failed terminal (no turn_complete), so no token usage
    is ever surfaced — the worker records honest zeros for the aborted turn."""

    async def _fake_stream_chat(messages, byok_dispatch=None):
        del messages, byok_dispatch
        from app.services.llm_stream import StreamChunk

        yield StreamChunk(delta="partial", done=False)
        raise RuntimeError("connection dropped mid-stream")

    with patch(
        "app.services.tutor_orchestrator_stream.stream_chat",
        _fake_stream_chat,
    ):
        events = []
        async for ev in orchestrate_stream(
            turn_id="t_die",
            user_id="u_die",
            user_message="hi",
            course_id=None,
            retrieved_chunks=None,
        ):
            events.append(ev)

    event_names = [e["event"] for e in events]
    assert "turn_complete" not in event_names
    assert event_names[-1] == "turn_failed"


@pytest.mark.asyncio
async def test_no_chunks_synth_prompt_omits_citation_contract() -> None:
    """When no chunks are present we must NOT advertise [L:<id>] in
    the prompt — a model that's told to cite with no excerpts will
    fabricate citation ids, poisoning the eval suite."""
    captured: dict = {}

    async def _fake_stream_chat(messages, byok_dispatch=None):  # S5: new kwarg
        captured["messages"] = messages
        from app.services.llm_stream import StreamChunk

        yield StreamChunk(delta="", done=True, usage={"cost_usd": 0.0})

    with patch(
        "app.services.tutor_orchestrator_stream.stream_chat",
        _fake_stream_chat,
    ):
        async for _ in orchestrate_stream(
            turn_id="t_no",
            user_id="u_no",
            user_message="anything",
            course_id=None,
            retrieved_chunks=None,
        ):
            pass

    system_text = captured["messages"][0].content
    assert "[L:" not in system_text
    assert "Lesson excerpts" not in system_text
