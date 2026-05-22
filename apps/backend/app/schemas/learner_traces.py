"""Pydantic DTOs for the learner + instructor trace surfaces.

Lumen v2 Phase I4. The companion shapes for ``app.api.v1.learner_traces``.

Two response shapes live here:

* :class:`TutorTurnTraceOut` — the full multi-agent trace for one
  tutor turn. Mirrors the admin observability drill-down shape
  (H7's :class:`~app.api.v1.admin_observability.LLMCallTraceOut`)
  but scoped to the learner's own conversation. The
  ``message_id`` + ``conversation_id`` are returned alongside the
  trace + audit lists so the frontend can render breadcrumbs +
  "show me the full conversation" deep-links without a second
  call. We also surface ``total_cost_usd`` / ``total_latency_ms``
  / token totals across every LLM call linked to the turn — that
  triple is what makes the "agents thinking on real money + real
  latency" portfolio shot legible at a glance.

* :class:`DraftReplayOut` — the instructor's per-draft replay
  shape. Same rows as the existing studio timeline (I3), but the
  replay surface needs the per-step timing duration explicitly +
  the total wall-clock duration so the auto-advance scrub bar can
  pace itself.

We re-define the row shapes here (rather than importing the H7 /
I3 router DTOs) so this module's surface is self-contained — H7's
:class:`LLMCallSummary` belongs to an admin router; importing it
into a learner-facing module would couple two surfaces with
different auth + retention contracts. The trace step + retrieval
audit DTOs are intentionally similar to H7's projections but live
under ``schemas/`` because the I4 surface is the second consumer
and a shared schema location matches the rest of the codebase's
shape.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMCallSummary(BaseModel):
    """Slim ``LLMCall`` projection for the learner-facing trace view.

    Same field set as H7's admin summary minus ``user_id`` (the
    learner already knows it's their own call) and ``error_kind``
    (we never expose vendor error class names to learners — they
    leak provider details + add no UX value). The provider /
    model strings stay because they're what the recruiter-facing
    demo wants to *show off*: "this turn ran on Groq Llama 3.3
    70B and cost $0.000023" — that's the legibility shot.
    """

    model_config = ConfigDict(from_attributes=True)

    call_id: str
    feature: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_ms: int
    status: str
    created_at: datetime


class TraceStepOut(BaseModel):
    """One ``agent_traces`` row on the wire (I4 projection).

    ``payload`` is passed through as an open object; the frontend
    dispatches on ``step`` to pick the right renderer (the same
    pattern as I2's per-tool ``ToolDetails`` component).
    """

    model_config = ConfigDict(from_attributes=True)

    trace_id: str
    parent_trace_id: str | None
    parent_call_id: str | None
    step: str
    step_index: int
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int
    status: str
    created_at: datetime


class RetrievalAuditOut(BaseModel):
    """One ``retrieval_audits`` row on the wire (I4 projection).

    Only the ``chunks`` JSONB column is structurally open — the
    frontend renders each chunk as a row with lesson id + score
    + excerpt. We don't ship a ``user_id`` (own-row context) but
    keep ``course_id`` so the chunk-list renderer can deep-link
    each lesson if needed.
    """

    model_config = ConfigDict(from_attributes=True)

    audit_id: str
    feature: str
    query: str
    course_id: str | None
    chunks: list[dict[str, Any]] = Field(default_factory=list)
    top_score: float | None
    created_at: datetime


class TutorTurnTraceOut(BaseModel):
    """End-to-end trace payload for one tutor turn.

    The ``llm_call`` slot is nullable because the orchestrator's
    :func:`_call_planner` / synthesiser path doesn't yet return
    the persisted ``llm_calls`` row id back through
    ``call_logged`` (see the orchestrator's comment near
    ``planner_call_id = None``). When that link arrives, the slot
    populates; until then the trace rows are still complete on
    their own — ``agent_traces`` rows + ``retrieval_audits`` give
    the full picture.

    The three roll-up fields (``total_cost_usd``,
    ``total_latency_ms``, ``total_tokens``) are summed across all
    LLM calls attributed to the turn by the temporal heuristic
    (same window the audit join uses) so the frontend can render
    "this turn cost $0.000023, ran in 950ms, used 180 tokens"
    without re-aggregating client-side.
    """

    message_id: str
    conversation_id: str
    course_id: str
    feature: str
    llm_call: LLMCallSummary | None = None
    agent_traces: list[TraceStepOut] = Field(default_factory=list)
    retrieval_audits: list[RetrievalAuditOut] = Field(default_factory=list)
    total_cost_usd: Decimal = Decimal("0")
    total_latency_ms: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    confidence: int = 0
    created_at: datetime


class DraftReplayStep(BaseModel):
    """One ``course_draft_traces`` row for the replay surface.

    Same field shape as I3's studio timeline endpoint's step
    projection — duplicated here so the replay surface doesn't
    import the authoring router's private DTOs.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    draft_id: str
    course_id: str | None
    step: str
    step_index: int
    status: str
    duration_ms: int
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DraftReplayOut(BaseModel):
    """End-to-end replay payload for one instructor draft.

    ``total_duration_ms`` is summed across every step so the
    auto-advance scrub bar can pace itself proportionally rather
    than per-step. ``step_count`` is denormalised for convenience
    — the same number is ``len(steps)`` but consumers that only
    need the count for a header label shouldn't have to walk the
    whole array.
    """

    course_id: str
    draft_id: str | None
    steps: list[DraftReplayStep] = Field(default_factory=list)
    step_count: int = 0
    total_duration_ms: int = 0


__all__ = [
    "DraftReplayOut",
    "DraftReplayStep",
    "LLMCallSummary",
    "RetrievalAuditOut",
    "TraceStepOut",
    "TutorTurnTraceOut",
]
