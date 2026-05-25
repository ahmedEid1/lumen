"""Learner + instructor trace-fetching service (Lumen v2 Phase I4).

Read-only joins across ``tutor_conversations`` / ``tutor_messages``
/ ``agent_traces`` / ``llm_calls`` / ``retrieval_audits`` for the
**learner**'s view of one tutor turn's reasoning chain, and across
``course_draft_traces`` for the **instructor**'s replay surface.

The two public entry points:

* :func:`fetch_tutor_turn_trace` — given a learner + a
  ``(conversation_id, message_id)`` pair, return the full trace
  for that turn. The learner must own the conversation (else
  403) and the message must belong to it (else 404).

* :func:`fetch_draft_replay` — given an instructor + a
  ``course_id``, return the trace rows for the latest draft of
  that course in a replay-ready shape (step ordering by
  ``step_index``, duration roll-up). Reuses I3's
  :func:`authoring_orchestrator.list_traces_for_course` so the
  "latest draft" selection logic stays in one place.

**Tutor-turn → trace linkage**. Today's I2 orchestrator does NOT
link an ``agent_traces`` row directly to a ``tutor_messages`` row
— traces carry ``user_id`` + ``feature`` + ``created_at`` but
not the persisted assistant message's id (the orchestrator runs
before the message is persisted, and ``call_logged`` doesn't yet
return the ``llm_calls.id`` either; both are documented gaps in
``tutor_orchestrator.py``). We therefore reconstruct the link
**temporally**: every ``agent_traces`` row whose ``user_id``
matches the learner AND whose ``created_at`` falls in the window
ending at the assistant message's ``created_at`` AND beginning a
generous 120 seconds before it. The H7 admin surface uses a
60-second window for the audit join; the trace window is wider
because the planner-to-synthesiser round trip on a complex turn
can sit at the upper edge of a minute (planner + retriever +
re-plan + web search + synth) and we'd rather over-pull a stray
sibling than under-pull and produce an empty timeline.

When I2 later adds a ``parent_message_id`` column on
``agent_traces`` (currently noted as a TODO in the orchestrator
docstring), this service swaps the temporal window for an exact
FK lookup with no API surface change.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.agent_trace import AgentTrace
from app.models.course_draft_trace import CourseDraftTrace
from app.models.llm_call import LLMCall
from app.models.retrieval_audit import RetrievalAudit
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.schemas.learner_traces import (
    DraftReplayOut,
    DraftReplayStep,
    LLMCallSummary,
    RetrievalAuditOut,
    TraceStepOut,
    TutorTurnTraceOut,
)
from app.services import authoring_orchestrator

log = get_logger(__name__)


# Window we look back from the assistant message's ``created_at``
# when joining ``agent_traces`` + ``llm_calls`` + ``retrieval_audits``.
# Generous because a complex multi-agent turn (planner +
# retriever + re-plan + web search + synth) can sit close to a
# minute; 120 s leaves room for slow upstreams without pulling in
# obviously-unrelated activity from the same user.
_TRACE_WINDOW_SECONDS = 120

# Tutor orchestrator's root feature slug — every trace + LLM call
# the orchestrator emits is namespaced under this prefix
# (``tutor.multi_agent.plan|replan|synth`` for LLM calls; the
# tracer rows themselves use the base slug ``tutor.multi_agent``).
# We filter on ``startswith`` to catch both.
_TUTOR_FEATURE_PREFIX = "tutor.multi_agent"

# How many retrieval audits we surface at most per turn. The
# orchestrator can in principle write more than one audit row
# per turn (retriever ran twice across plan + re-plan), but
# practical observed runs cap out at 2-3. Five is a comfortable
# upper bound that keeps the JSON payload small.
_AUDIT_LIMIT = 5


# ---------- Tutor turn trace ----------


async def fetch_tutor_turn_trace(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    message_id: str,
) -> TutorTurnTraceOut:
    """Walk the trace tables and return the per-turn drill-down payload.

    Authorization model:

    * The conversation must exist and belong to ``user_id``. We
      raise :class:`ForbiddenError` (403) when the conversation
      exists but is owned by someone else — explicit ownership
      check rather than the "collapse to 404" posture the tutor
      list endpoint takes. Rationale: a trace deep-link is shared
      via URL, so a learner clicking a friend's link should see
      a clear "this isn't yours" rather than "this conversation
      doesn't exist" (the latter is the right posture for
      enumeration probes, but trace URLs aren't enumerated).
    * The message must exist AND belong to the conversation. A
      stranger message id → 404.
    * The message must be an *assistant* turn. We never trace a
      user turn (there's nothing to trace — the orchestrator
      hasn't run yet when the user turn lands). A user message
      id → 404 (same posture as a missing one — both are "no
      trace for this id").

    Returns a fully-populated :class:`TutorTurnTraceOut` even
    when there's no trace recorded (e.g. a refused / empty-
    retrieval turn that didn't go through the orchestrator).
    Empty lists + zero roll-ups are the right "nothing happened"
    signal; the frontend renders a "no plan ran" state in that
    case rather than blowing up.
    """
    conversation = await db.get(TutorConversation, conversation_id)
    if conversation is None:
        raise NotFoundError(
            "Conversation not found",
            code="trace.conversation_not_found",
            details={"conversation_id": conversation_id},
        )
    if conversation.user_id != user_id:
        raise ForbiddenError(
            "Not your conversation",
            code="trace.forbidden",
            details={"conversation_id": conversation_id},
        )

    message = await db.get(TutorMessage, message_id)
    if message is None or message.conversation_id != conversation_id:
        raise NotFoundError(
            "Message not found",
            code="trace.message_not_found",
            details={"message_id": message_id},
        )
    # Refuse to surface a trace for a user turn — there is none.
    if str(message.role) != str(TutorMessageRole.assistant):
        raise NotFoundError(
            "Trace is only available for assistant turns",
            code="trace.not_assistant_turn",
            details={"message_id": message_id, "role": str(message.role)},
        )

    window_end = message.created_at
    window_start = window_end - timedelta(seconds=_TRACE_WINDOW_SECONDS)

    # 1. Pull every agent_traces row for this user in the window
    #    whose feature is the tutor's multi-agent namespace. The
    #    ``ix_agent_traces_user_created`` composite index makes
    #    this an index range scan.
    trace_rows = (
        (
            await db.execute(
                select(AgentTrace)
                .where(
                    AgentTrace.user_id == user_id,
                    AgentTrace.feature.startswith(_TUTOR_FEATURE_PREFIX),
                    AgentTrace.created_at >= window_start,
                    AgentTrace.created_at <= window_end,
                )
                .order_by(
                    AgentTrace.created_at.asc(),
                    AgentTrace.step_index.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    # 2. Pull every LLM call for this user in the same window with
    #    a tutor-multi-agent feature slug. We need the slim
    #    summary plus the totals roll-up.
    llm_rows = (
        (
            await db.execute(
                select(LLMCall)
                .where(
                    LLMCall.user_id == user_id,
                    LLMCall.feature.startswith(_TUTOR_FEATURE_PREFIX),
                    LLMCall.created_at >= window_start,
                    LLMCall.created_at <= window_end,
                )
                .order_by(LLMCall.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    # 3. Pull retrieval audits in the same window for this user.
    #    Tutor retrievals are written by the retriever sub-agent
    #    with feature ``tutor.multi_agent.retriever`` (see
    #    ``tutor_subagents.run_retriever``), so a prefix filter
    #    catches them without listing every sub-agent slug.
    audit_rows = (
        (
            await db.execute(
                select(RetrievalAudit)
                .where(
                    RetrievalAudit.user_id == user_id,
                    RetrievalAudit.created_at >= window_start,
                    RetrievalAudit.created_at <= window_end,
                )
                .order_by(desc(RetrievalAudit.created_at))
                .limit(_AUDIT_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    # ---------- Project to DTOs ----------

    traces_out = [_trace_to_out(r) for r in trace_rows]
    audits_out = [_audit_to_out(r) for r in audit_rows]

    # Pick the "main" LLM call to surface — the synthesiser call
    # is the one with the user-visible answer attached, so we
    # prefer the most recent ``.synth`` feature row. Fall back to
    # the most recent call of any tutor feature, or None.
    main_call: LLMCall | None = None
    synth_calls = [r for r in llm_rows if r.feature.endswith(".synth")]
    if synth_calls:
        main_call = synth_calls[-1]
    elif llm_rows:
        main_call = llm_rows[-1]
    llm_summary = _llm_to_summary(main_call) if main_call else None

    # Roll up cost / latency / tokens across every LLM call we
    # found. This is what powers the "this turn cost $X, ran in
    # Yms, used Z tokens" badge at the top of the page.
    total_cost = sum(
        (Decimal(str(r.cost_usd)) for r in llm_rows),
        start=Decimal("0"),
    )
    total_latency = sum(int(r.latency_ms) for r in llm_rows)
    total_prompt = sum(int(r.prompt_tokens) for r in llm_rows)
    total_completion = sum(int(r.completion_tokens) for r in llm_rows)

    # Pull the confidence score out of the plan step's payload if
    # we have one. The orchestrator writes
    # ``payload["confidence_after_plan"]`` on the ``plan`` step;
    # the re-planner may overwrite via ``payload["decoded"]
    # ["confidence_now"]`` on the ``replan`` step. We pick the
    # last confidence we see (re-plan overrides plan).
    confidence = 0
    for row in trace_rows:
        payload = row.payload or {}
        if row.step == "plan":
            with contextlib.suppress(TypeError, ValueError):
                confidence = int(payload.get("confidence_after_plan", confidence))
        elif row.step == "replan":
            decoded = payload.get("decoded") if isinstance(payload, dict) else None
            if isinstance(decoded, dict):
                with contextlib.suppress(TypeError, ValueError):
                    confidence = int(decoded.get("confidence_now", confidence))

    log.info(
        "learner_trace_fetched",
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        trace_rows=len(traces_out),
        llm_calls=len(llm_rows),
        audits=len(audits_out),
    )

    return TutorTurnTraceOut(
        message_id=message_id,
        conversation_id=conversation_id,
        course_id=conversation.course_id,
        feature=_TUTOR_FEATURE_PREFIX,
        llm_call=llm_summary,
        agent_traces=traces_out,
        retrieval_audits=audits_out,
        total_cost_usd=total_cost,
        total_latency_ms=total_latency,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        confidence=confidence,
        created_at=message.created_at,
    )


# ---------- Draft replay ----------


async def fetch_draft_replay(db: AsyncSession, *, course_id: str) -> DraftReplayOut:
    """Return the replay payload for the latest draft of ``course_id``.

    Reuses I3's :func:`authoring_orchestrator.list_traces_for_course`
    so "latest draft" semantics (most-recent ``draft_id`` for the
    course) stay defined in one place. The caller (the API
    handler) is responsible for the ownership check — we
    deliberately don't gate here because both the studio timeline
    endpoint (I3) and this replay endpoint (I4) share the same
    "instructor owns the course OR is admin" rule and the API
    layer is the natural place for that.
    """
    rows = await authoring_orchestrator.list_traces_for_course(db, course_id=course_id)

    steps_out = [_draft_to_out(r) for r in rows]
    total_duration = sum(int(r.duration_ms) for r in rows)
    draft_id = rows[0].draft_id if rows else None

    return DraftReplayOut(
        course_id=course_id,
        draft_id=draft_id,
        steps=steps_out,
        step_count=len(steps_out),
        total_duration_ms=total_duration,
    )


# ---------- DTO helpers ----------


def _trace_to_out(row: AgentTrace) -> TraceStepOut:
    return TraceStepOut(
        trace_id=row.id,
        parent_trace_id=row.parent_trace_id,
        parent_call_id=row.parent_call_id,
        step=row.step,
        step_index=row.step_index,
        payload=dict(row.payload or {}),
        duration_ms=row.duration_ms,
        status=row.status,
        created_at=row.created_at,
    )


def _llm_to_summary(row: LLMCall) -> LLMCallSummary:
    return LLMCallSummary(
        call_id=row.id,
        feature=row.feature,
        provider=row.provider,
        model=row.model,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        cost_usd=row.cost_usd,
        latency_ms=row.latency_ms,
        status=row.status,
        created_at=row.created_at,
    )


def _audit_to_out(row: RetrievalAudit) -> RetrievalAuditOut:
    return RetrievalAuditOut(
        audit_id=row.id,
        feature=row.feature,
        query=row.query,
        course_id=row.course_id,
        chunks=list(row.chunks or []),
        top_score=row.top_score,
        created_at=row.created_at,
    )


def _draft_to_out(row: CourseDraftTrace) -> DraftReplayStep:
    return DraftReplayStep(
        id=row.id,
        draft_id=row.draft_id,
        course_id=row.course_id,
        step=row.step,
        step_index=row.step_index,
        status=row.status,
        duration_ms=row.duration_ms,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )


__all__ = [
    "fetch_draft_replay",
    "fetch_tutor_turn_trace",
]
