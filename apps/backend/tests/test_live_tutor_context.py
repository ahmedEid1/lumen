"""L25, L26, L39: the live (streamed) tutor names the course, sees recent
turns, retrieves follow-ups in context, and says when course search failed."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.llm_stream import StreamChunk
from app.services.tutor_orchestrator_stream import _build_synth_messages, orchestrate_stream
from app.services.tutor_turn_service import retrieval_query


def test_prompt_names_the_course_and_drops_the_programming_rule() -> None:
    msgs = _build_synth_messages("What is a mapped type?", None, course_title="Product Design")
    system = msgs[0].content
    assert '"Product Design"' in system
    assert "programming" not in system.lower()


def test_recent_turns_go_between_the_system_prompt_and_the_question() -> None:
    history = [
        {"role": "user", "content": "What is variance?"},
        {"role": "assistant", "content": "How subtyping carries over to generics [L:abc]."},
    ]
    msgs = _build_synth_messages("Explain that more simply", None, history=history)
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1].content == "What is variance?"
    assert msgs[-1].content == "Explain that more simply"


def test_history_is_capped_at_six_messages() -> None:
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(10)
    ]
    msgs = _build_synth_messages("now?", None, history=history)
    assert [m.content for m in msgs[1:-1]] == ["m4", "m5", "m6", "m7", "m8", "m9"]


def test_short_follow_up_retrieves_with_the_previous_question() -> None:
    history = [
        {"role": "user", "content": "How does HNSW search work?"},
        {"role": "assistant", "content": "It walks a layered graph."},
    ]
    assert (
        retrieval_query("Why is it fast?", history) == "How does HNSW search work?\nWhy is it fast?"
    )
    long_question = (
        "What is the difference between cosine distance and dot product similarity in pgvector?"
    )
    assert retrieval_query(long_question, history) == long_question
    assert retrieval_query("Why?", []) == "Why?"


@pytest.mark.asyncio
async def test_failed_course_search_is_reported_not_hidden() -> None:
    captured: dict = {}

    async def _fake_stream_chat(messages, byok_dispatch=None):
        captured["messages"] = messages
        yield StreamChunk(delta="ok", done=False, usage={})
        yield StreamChunk(delta="", done=True, usage={"cost_usd": 0.0})

    events = []
    with patch("app.services.tutor_orchestrator_stream.stream_chat", _fake_stream_chat):
        async for ev in orchestrate_stream(
            turn_id="t",
            user_id="u",
            user_message="What is RAG?",
            course_id="c",
            retrieved_chunks=None,
            course_title="Building a RAG system from scratch",
            retrieval_failed=True,
        ):
            events.append(ev)

    result = next(e for e in events if e["event"] == "tool_call_result")
    assert result["data"]["status"] == "error"
    assert result["data"]["summary"] == "course search failed"
    assert "couldn't check the course materials" in captured["messages"][0].content
