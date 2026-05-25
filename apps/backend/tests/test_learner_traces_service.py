"""Learner-traces service tests (Lumen v2 Phase I4).

Cover the trace-fetching service shape + auth invariants:

* Owner gets a populated trace with the expected fields.
* Non-owner raises :class:`ForbiddenError`.
* Missing conversation / missing message raise
  :class:`NotFoundError`.
* The cost / latency / token roll-up sums correctly across
  multiple LLM calls in the window.
* The confidence is picked up from the planner's payload (and
  overridden by the re-planner when present).
* The draft replay shape exposes the expected fields.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.agent_trace import TRACE_STATUS_OK, AgentTrace
from app.models.course_draft_trace import (
    DRAFT_STATUS_OK,
    DRAFT_STEP_OUTLINER,
    DRAFT_STEP_RESEARCHER,
    CourseDraftTrace,
)
from app.models.llm_call import STATUS_OK, LLMCall
from app.models.retrieval_audit import RetrievalAudit
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Subject,
)
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.user import Role


async def _ensure_course(db: AsyncSession, *, course_id: str, owner_id: str) -> None:
    """Idempotently seed a minimal published course for the FK target.

    ``tutor_conversations.course_id`` has a NOT NULL FK into
    ``courses``. Tests that hardcode a course id need an actual row
    behind it. Reuse a single subject keyed on the id so calls within
    a single test don't double-insert.
    """
    existing = await db.get(Course, course_id)
    if existing is not None:
        return
    subj = Subject(
        title=f"Subject {course_id}", slug=f"subj-{course_id.replace('_', '-')}"
    )
    db.add(subj)
    await db.flush()
    db.add(
        Course(
            id=course_id,
            owner_id=owner_id,
            subject_id=subj.id,
            title=f"Course {course_id}",
            slug=f"course-{course_id.replace('_', '-')}",
            overview="seed",
            difficulty=Difficulty.beginner,
            status=CourseStatus.published,
        )
    )
    await db.flush()
from app.services.learner_traces import (
    fetch_draft_replay,
    fetch_tutor_turn_trace,
)


async def _make_conv_with_turn(
    db: AsyncSession,
    *,
    user_id: str,
    course_id: str = "crs_test_001",
    assistant_content: str = "Here's the answer.",
) -> tuple[TutorConversation, TutorMessage]:
    """Seed one conversation + one user turn + one assistant turn.

    Returns the assistant message so the caller can use its
    ``created_at`` as the trace window anchor.
    """
    await _ensure_course(db, course_id=course_id, owner_id=user_id)
    conv = TutorConversation(user_id=user_id, course_id=course_id)
    db.add(conv)
    await db.flush()
    user_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.user,
        content="What's photosynthesis?",
        citations=[],
    )
    db.add(user_msg)
    asst_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.assistant,
        content=assistant_content,
        citations=[],
    )
    db.add(asst_msg)
    await db.commit()
    await db.refresh(conv)
    await db.refresh(asst_msg)
    return conv, asst_msg


async def _seed_trace(
    db: AsyncSession,
    *,
    user_id: str,
    step: str,
    step_index: int,
    payload: dict | None = None,
    feature: str = "tutor.multi_agent",
    when: datetime | None = None,
) -> AgentTrace:
    row = AgentTrace(
        user_id=user_id,
        feature=feature,
        step=step,
        step_index=step_index,
        payload=payload or {},
        duration_ms=120,
        status=TRACE_STATUS_OK,
    )
    db.add(row)
    await db.flush()
    if when is not None:
        # We backdate via raw SQL because ``created_at`` is
        # server-default; the ORM won't include it in the UPDATE
        # otherwise. The test needs deterministic windowing.
        await db.execute(
            text("update agent_traces set created_at = :ts where id = :id"),
            {"ts": when, "id": row.id},
        )
        await db.flush()
    await db.refresh(row)
    return row


async def _seed_llm_call(
    db: AsyncSession,
    *,
    user_id: str,
    feature: str = "tutor.multi_agent.synth",
    cost: str = "0.000123",
    latency_ms: int = 850,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    when: datetime | None = None,
) -> LLMCall:
    row = LLMCall(
        user_id=user_id,
        feature=feature,
        provider="openai",
        model="llama-3.3-70b-versatile",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=Decimal(cost),
        latency_ms=latency_ms,
        status=STATUS_OK,
    )
    db.add(row)
    await db.flush()
    if when is not None:
        await db.execute(
            text("update llm_calls set created_at = :ts where id = :id"),
            {"ts": when, "id": row.id},
        )
        await db.flush()
    await db.refresh(row)
    return row


async def _seed_audit(
    db: AsyncSession,
    *,
    user_id: str,
    course_id: str = "crs_test_001",
    when: datetime | None = None,
) -> RetrievalAudit:
    row = RetrievalAudit(
        user_id=user_id,
        feature="tutor.multi_agent.retriever",
        query="photosynthesis",
        course_id=course_id,
        chunks=[
            {
                "chunk_id": "cnk_a",
                "lesson_id": "lsn_a",
                "score": 0.12,
                "snippet": "Plants make food from sunlight.",
            }
        ],
        top_score=0.12,
    )
    db.add(row)
    await db.flush()
    if when is not None:
        await db.execute(
            text("update retrieval_audits set created_at = :ts where id = :id"),
            {"ts": when, "id": row.id},
        )
        await db.flush()
    await db.refresh(row)
    return row


# ---------- Auth invariants ----------


async def test_owner_gets_populated_trace(
    db_session: AsyncSession, make_user
) -> None:
    """A learner with traces in the time window gets the full shape."""
    user = await make_user(role=Role.student)
    _conv, asst = await _make_conv_with_turn(db_session, user_id=user.id)

    # Seed traces + LLM call + audit slightly before the assistant
    # message — all within the 120-second window.
    when = asst.created_at - timedelta(seconds=5)
    plan = await _seed_trace(
        db_session,
        user_id=user.id,
        step="plan",
        step_index=0,
        payload={
            "tool_calls": [{"tool_name": "retriever"}],
            "confidence_after_plan": 4,
        },
        when=when,
    )
    await _seed_trace(
        db_session,
        user_id=user.id,
        step="tool_call",
        step_index=1,
        payload={"tool_name": "retriever"},
        when=when + timedelta(milliseconds=10),
    )
    await _seed_llm_call(
        db_session,
        user_id=user.id,
        feature="tutor.multi_agent.synth",
        when=when + timedelta(seconds=1),
    )
    await _seed_audit(db_session, user_id=user.id, when=when)
    await db_session.commit()

    result = await fetch_tutor_turn_trace(
        db_session,
        user_id=user.id,
        conversation_id=_conv.id,
        message_id=asst.id,
    )

    assert result.message_id == asst.id
    assert result.conversation_id == _conv.id
    assert result.course_id == _conv.course_id
    assert len(result.agent_traces) >= 2
    assert result.agent_traces[0].step == "plan"
    assert result.llm_call is not None
    assert result.llm_call.feature == "tutor.multi_agent.synth"
    assert result.llm_call.provider == "openai"
    assert len(result.retrieval_audits) == 1
    assert result.confidence == 4
    assert result.total_latency_ms == 850
    assert result.total_prompt_tokens == 100
    assert result.total_completion_tokens == 50
    assert result.total_cost_usd == Decimal("0.000123")
    # The trace we seeded should be present in the projected list.
    trace_ids = {t.trace_id for t in result.agent_traces}
    assert plan.id in trace_ids


async def test_non_owner_raises_forbidden(
    db_session: AsyncSession, make_user
) -> None:
    owner = await make_user(role=Role.student)
    stranger = await make_user(role=Role.student)
    conv, asst = await _make_conv_with_turn(db_session, user_id=owner.id)

    with pytest.raises(ForbiddenError):
        await fetch_tutor_turn_trace(
            db_session,
            user_id=stranger.id,
            conversation_id=conv.id,
            message_id=asst.id,
        )


async def test_missing_conversation_raises_not_found(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(role=Role.student)
    with pytest.raises(NotFoundError):
        await fetch_tutor_turn_trace(
            db_session,
            user_id=user.id,
            conversation_id="conv_does_not_exist",
            message_id="msg_anything",
        )


async def test_missing_message_raises_not_found(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(role=Role.student)
    conv, _ = await _make_conv_with_turn(db_session, user_id=user.id)

    with pytest.raises(NotFoundError):
        await fetch_tutor_turn_trace(
            db_session,
            user_id=user.id,
            conversation_id=conv.id,
            message_id="msg_nope",
        )


async def test_user_turn_id_raises_not_found(
    db_session: AsyncSession, make_user
) -> None:
    """A trace can only be requested for an assistant turn."""
    user = await make_user(role=Role.student)
    await _ensure_course(db_session, course_id="crs_x", owner_id=user.id)
    conv = TutorConversation(user_id=user.id, course_id="crs_x")
    db_session.add(conv)
    await db_session.flush()
    user_msg = TutorMessage(
        conversation_id=conv.id,
        role=TutorMessageRole.user,
        content="hi",
        citations=[],
    )
    db_session.add(user_msg)
    await db_session.commit()
    await db_session.refresh(user_msg)

    with pytest.raises(NotFoundError):
        await fetch_tutor_turn_trace(
            db_session,
            user_id=user.id,
            conversation_id=conv.id,
            message_id=user_msg.id,
        )


# ---------- Roll-up + confidence ----------


async def test_cost_latency_token_rollup(
    db_session: AsyncSession, make_user
) -> None:
    """Multiple LLM calls in the window sum into the totals."""
    user = await make_user(role=Role.student)
    conv, asst = await _make_conv_with_turn(db_session, user_id=user.id)
    base = asst.created_at - timedelta(seconds=10)

    await _seed_llm_call(
        db_session,
        user_id=user.id,
        feature="tutor.multi_agent.plan",
        cost="0.000050",
        latency_ms=200,
        prompt_tokens=40,
        completion_tokens=20,
        when=base,
    )
    await _seed_llm_call(
        db_session,
        user_id=user.id,
        feature="tutor.multi_agent.synth",
        cost="0.000200",
        latency_ms=600,
        prompt_tokens=120,
        completion_tokens=60,
        when=base + timedelta(seconds=2),
    )
    await db_session.commit()

    result = await fetch_tutor_turn_trace(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        message_id=asst.id,
    )
    assert result.total_latency_ms == 800
    assert result.total_prompt_tokens == 160
    assert result.total_completion_tokens == 80
    assert result.total_cost_usd == Decimal("0.000250")
    # Synth call is preferred as the surfaced ``llm_call``.
    assert result.llm_call is not None
    assert result.llm_call.feature == "tutor.multi_agent.synth"


async def test_replan_overrides_plan_confidence(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(role=Role.student)
    conv, asst = await _make_conv_with_turn(db_session, user_id=user.id)
    base = asst.created_at - timedelta(seconds=5)
    await _seed_trace(
        db_session,
        user_id=user.id,
        step="plan",
        step_index=0,
        payload={"confidence_after_plan": 3},
        when=base,
    )
    await _seed_trace(
        db_session,
        user_id=user.id,
        step="replan",
        step_index=2,
        payload={"decoded": {"needs_more": False, "confidence_now": 5}},
        when=base + timedelta(milliseconds=20),
    )
    await db_session.commit()

    result = await fetch_tutor_turn_trace(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        message_id=asst.id,
    )
    assert result.confidence == 5


async def test_empty_window_returns_zero_rollups(
    db_session: AsyncSession, make_user
) -> None:
    """A refused / empty-retrieval turn → empty lists, zero totals."""
    user = await make_user(role=Role.student)
    conv, asst = await _make_conv_with_turn(db_session, user_id=user.id)
    # No traces / LLM calls / audits seeded.
    result = await fetch_tutor_turn_trace(
        db_session,
        user_id=user.id,
        conversation_id=conv.id,
        message_id=asst.id,
    )
    assert result.agent_traces == []
    assert result.retrieval_audits == []
    assert result.llm_call is None
    assert result.total_cost_usd == Decimal("0")
    assert result.total_latency_ms == 0
    assert result.confidence == 0


# ---------- Draft replay ----------


async def test_draft_replay_returns_steps_and_totals(
    db_session: AsyncSession, make_user
) -> None:
    user = await make_user(role=Role.instructor)
    course_id = "crs_draft_replay_001"
    await _ensure_course(db_session, course_id=course_id, owner_id=user.id)
    draft_id = uuid.uuid4().hex[:16]

    row1 = CourseDraftTrace(
        draft_id=draft_id,
        user_id=user.id,
        course_id=course_id,
        step=DRAFT_STEP_RESEARCHER,
        step_index=0,
        payload={"prompt_summary": "research", "response_summary": "ok"},
        duration_ms=120,
        status=DRAFT_STATUS_OK,
    )
    row2 = CourseDraftTrace(
        draft_id=draft_id,
        user_id=user.id,
        course_id=course_id,
        step=DRAFT_STEP_OUTLINER,
        step_index=1,
        payload={"prompt_summary": "outline", "response_summary": "ok"},
        duration_ms=200,
        status=DRAFT_STATUS_OK,
    )
    db_session.add(row1)
    db_session.add(row2)
    await db_session.commit()

    result = await fetch_draft_replay(db_session, course_id=course_id)

    assert result.course_id == course_id
    assert result.draft_id == draft_id
    assert result.step_count == 2
    assert result.total_duration_ms == 320
    assert [s.step for s in result.steps] == [
        DRAFT_STEP_RESEARCHER,
        DRAFT_STEP_OUTLINER,
    ]


async def test_draft_replay_returns_empty_for_unknown_course(
    db_session: AsyncSession,
) -> None:
    result = await fetch_draft_replay(
        db_session, course_id="crs_no_draft_ever"
    )
    assert result.step_count == 0
    assert result.steps == []
    assert result.draft_id is None
    assert result.total_duration_ms == 0
