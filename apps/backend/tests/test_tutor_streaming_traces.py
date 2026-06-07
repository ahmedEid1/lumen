"""Streamed tutor turns must surface a real timeline on the trace drill-down.

Follow-up to the 2026-06-06 persistence fix (BACKLOG P3): the drill-down
page ``/dashboard/tutor/{conv}/turn/{msg}`` resolves for streamed turns
but showed an empty step timeline and $0/0ms/0tok AGENT RUN TOTALS. Root
cause is a feature-string mismatch, not missing data plumbing:
``fetch_tutor_turn_trace`` reconstructs the turn temporally but filters
both ``agent_traces`` and ``llm_calls`` on
``feature.startswith("tutor.multi_agent")`` — while the streaming worker
stamped its retriever trace ``tutor.streaming`` and its llm_calls row
``tutor.stream``. Rows existed; the filter dropped them.

Contract under test (mirrors the non-streaming vocabulary so
``TraceTimeline`` renders both paths identically):

1. The worker records ``plan`` (step_index 0) → ``sub_agent.retriever``
   (1, parented to plan) → ``synthesis`` (2, parented to plan), all
   ``feature="tutor.multi_agent"``.
2. The success-path ``llm_calls`` row carries
   ``feature="tutor.multi_agent.synth"`` (the ``.synth`` suffix makes it
   the drill-down's main call and feeds the totals); failure-path rows
   keep ``tutor.stream``. The request-count quota is feature-agnostic
   (COUNT over user+window), so the re-feature cannot change quota math.
3. End to end: ``fetch_tutor_turn_trace`` for the streamed turn returns
   the three steps and non-empty LLM totals.

DB-backed like test_tutor_streaming_message_persistence.py: the worker's
``make_worker_engine`` resolves to the transient test DB; only the
Redis/cost seams are patched. ``run_retriever`` runs REAL against an
(empty) course — it records its trace row regardless of hit count.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_trace import AgentTrace
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    ModerationState,
    Subject,
    Visibility,
)
from app.models.llm_call import LLMCall
from app.models.tutor_conversation import TutorConversation
from app.services import learner_traces as learner_traces_service
from app.services.tutor_turn_service import create_turn
from app.workers.tasks import tutor_streaming

QUESTION = "Why does retrieval bound the citation universe?"


def _patch_redis_seams(monkeypatch, emitted: list[dict]) -> None:
    redis_client = MagicMock()
    redis_client.aclose = AsyncMock()
    monkeypatch.setattr(
        tutor_streaming.redis.Redis, "from_url", MagicMock(return_value=redis_client)
    )

    async def _capture(_client, *, turn_id, event, data):
        emitted.append({"turn_id": turn_id, "event": event, "data": data})

    monkeypatch.setattr(tutor_streaming, "emit_event", _capture)
    monkeypatch.setattr(tutor_streaming, "set_stream_ttl", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "reconcile_cost", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "release_concurrency", AsyncMock())
    monkeypatch.setattr(tutor_streaming, "reserve_cost", AsyncMock(return_value=(True, "ok")))
    monkeypatch.setattr(tutor_streaming, "set_reserved_cost", AsyncMock(return_value=True))


async def _seed_turn(db_session: AsyncSession, make_user) -> tuple[str, str, str, str]:
    """user + course + conversation + pending turn; returns their ids."""
    user = await make_user(email=f"trace-{uuid.uuid4().hex[:6]}@lumen.test")
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"Trace {suffix}", slug=f"trace-{suffix}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title=f"Trace Course {suffix}",
        slug=f"trace-course-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
    )
    db_session.add(course)
    await db_session.flush()
    conv = TutorConversation(user_id=user.id, course_id=course.id)
    db_session.add(conv)
    await db_session.flush()
    turn = await create_turn(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        reserved_cost_usd=Decimal("0"),
        reservation_ip_key=None,
        prompt_template_hash=None,
        user_message=QUESTION,
        course_id=course.id,
        credential_id=None,
        enqueue_task=False,
    )
    await db_session.commit()
    return turn.id, conv.id, course.id, user.id


def _stub_stream_factory():
    async def _stub_stream(**_kw):
        yield {"event": "planner_start", "data": {"model": "stub-model", "route": "stream"}}
        yield {"event": "synth_chunk", "data": {"delta": "Retrieval bounds citations "}}
        yield {"event": "synth_chunk", "data": {"delta": "by construction."}}
        yield {
            "event": "turn_complete",
            "data": {
                "message_id": None,
                "cost_usd": 0.0021,
                "prompt_tokens": 111,
                "completion_tokens": 42,
                "first_token_ms": 9.0,
                "total_ms": 1234.0,
            },
        }

    return _stub_stream


async def test_streamed_turn_records_multi_agent_trace_steps(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    turn_id, _conv_id, _course_id, user_id = await _seed_turn(db_session, make_user)
    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _stub_stream_factory())
    emitted: list[dict] = []
    _patch_redis_seams(monkeypatch, emitted)

    await tutor_streaming._run_turn_async(turn_id)

    rows = (
        (
            await db_session.execute(
                select(AgentTrace)
                .where(
                    AgentTrace.user_id == user_id,
                    AgentTrace.feature.startswith("tutor.multi_agent"),
                )
                .order_by(AgentTrace.created_at, AgentTrace.step_index)
            )
        )
        .scalars()
        .all()
    )
    steps = [(r.step, r.step_index, r.feature) for r in rows]
    assert steps == [
        ("plan", 0, "tutor.multi_agent"),
        ("sub_agent.retriever", 1, "tutor.multi_agent"),
        ("synthesis", 2, "tutor.multi_agent"),
    ], f"unexpected trace rows: {steps}"

    plan, retriever, synthesis = rows
    assert retriever.parent_trace_id == plan.id
    assert synthesis.parent_trace_id == plan.id
    assert synthesis.payload.get("answer_head", "").startswith("Retrieval bounds citations")
    assert synthesis.duration_ms == 1234


async def test_streamed_success_llm_row_is_multi_agent_synth(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    turn_id, _conv_id, _course_id, user_id = await _seed_turn(db_session, make_user)
    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _stub_stream_factory())
    emitted: list[dict] = []
    _patch_redis_seams(monkeypatch, emitted)

    await tutor_streaming._run_turn_async(turn_id)

    calls = (
        (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id)))
        .scalars()
        .all()
    )
    features = sorted(c.feature for c in calls)
    assert "tutor.multi_agent.synth" in features, features
    synth_row = next(c for c in calls if c.feature == "tutor.multi_agent.synth")
    assert synth_row.prompt_tokens == 111
    assert synth_row.completion_tokens == 42


async def test_streamed_failure_llm_row_keeps_stream_feature(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Failure rows stay on tutor.stream so a failed attempt never
    pollutes a successful turn's drill-down totals."""
    turn_id, _conv_id, _course_id, user_id = await _seed_turn(db_session, make_user)

    async def _exploding_stream(**_kw):
        yield {"event": "planner_start", "data": {"model": "stub", "route": "stream"}}
        raise RuntimeError("provider blew up")

    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _exploding_stream)
    monkeypatch.setattr(tutor_streaming, "run_retriever", AsyncMock())
    emitted: list[dict] = []
    _patch_redis_seams(monkeypatch, emitted)

    with suppress(RuntimeError):
        await tutor_streaming._run_turn_async(turn_id)

    calls = (
        (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user_id)))
        .scalars()
        .all()
    )
    assert [c.feature for c in calls] == ["tutor.stream"], [c.feature for c in calls]

    # Pollution guard: the drill-down namespace must stay EMPTY for a
    # failed turn — committed multi_agent rows from a failed attempt
    # would leak into the user's next successful turn's 120s window.
    polluting = (
        (
            await db_session.execute(
                select(AgentTrace).where(
                    AgentTrace.user_id == user_id,
                    AgentTrace.feature.startswith("tutor.multi_agent"),
                )
            )
        )
        .scalars()
        .all()
    )
    assert polluting == [], [t.step for t in polluting]


async def test_drilldown_service_returns_streamed_timeline_and_totals(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """End-to-end page contract: the temporal-window reconstruction in
    fetch_tutor_turn_trace must surface the streamed turn's steps and
    real totals once the worker stamps the multi_agent namespace."""
    turn_id, conv_id, _course_id, user_id = await _seed_turn(db_session, make_user)
    monkeypatch.setattr(tutor_streaming, "orchestrate_stream", _stub_stream_factory())
    emitted: list[dict] = []
    _patch_redis_seams(monkeypatch, emitted)

    await tutor_streaming._run_turn_async(turn_id)

    completes = [e for e in emitted if e["event"] == "turn_complete"]
    assert completes and completes[0]["data"]["message_id"], "needs the persisted message id"
    message_id = completes[0]["data"]["message_id"]

    out = await learner_traces_service.fetch_tutor_turn_trace(
        db_session,
        user_id=user_id,
        conversation_id=conv_id,
        message_id=message_id,
    )
    step_names = [t.step for t in out.agent_traces]
    assert step_names == ["plan", "sub_agent.retriever", "synthesis"], step_names
    assert out.llm_call is not None, "the .synth row must surface as the main call"
    assert out.llm_call.feature == "tutor.multi_agent.synth"
    assert out.total_prompt_tokens == 111
    assert out.total_completion_tokens == 42
    assert out.total_latency_ms >= 1234
