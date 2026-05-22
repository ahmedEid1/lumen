"""AgentTrace — one row per step in an agentic flow.

Lumen v2 Phase H7. The substrate I2 (multi-agent tutor) and I3
(self-critique authoring) will write into. Every step of an agentic
workflow — a planner picking a tool, a sub-agent fetching context,
a critic scoring a draft, a reviser rewriting it — lands here as
one row, with a JSON ``payload`` carrying whatever fields the step
needs to capture and a ``parent_trace_id`` link that builds the
tree.

The relationship to ``llm_calls`` is **lateral, not vertical**:

* The cost meter (H1) records *every LLM round-trip* in
  ``llm_calls``, one row per ``provider.chat()`` call.
* The agent tracer (H7) records *every agentic step* in
  ``agent_traces``, one row per planner/tool/sub-agent/critic step.

A single LLM round-trip (one ``llm_calls`` row) is usually the
"work" of one agent step (one ``agent_traces`` row); the link
between them is ``agent_traces.parent_call_id`` → ``llm_calls.id``.
But some steps don't make an LLM call at all (a tool execution,
a deterministic plan), so ``parent_call_id`` is nullable.

Tree shape. ``parent_trace_id`` lets a planner step parent its
sub-agent steps; the dashboard renders the tree with indentation +
connecting lines. ``step_index`` provides total-ordering within a
turn so siblings render left-to-right in call order.

Schema fields:

* ``trace_id`` — 21-char nanoid, primary key.
* ``parent_call_id`` — FK → ``llm_calls.id`` (nullable). The
  cost-meter row spawned by this step's underlying LLM call, if any.
* ``user_id`` — same ``"__system__"`` sentinel convention as
  ``llm_calls`` for system-initiated work (eval suite, batch jobs).
  NOT NULL so the ``(user_id, created_at)`` composite index is dense.
* ``feature`` — short slug. Conventions mirror ``llm_calls.feature``
  but tend to be more specific: ``"tutor.multi_agent"``,
  ``"authoring.critique_revise"``, etc.
* ``step`` — what this step *is*. Open-ended string so I2/I3 can add
  new step kinds without a migration: ``"plan"``, ``"tool_call"``,
  ``"sub_agent.retriever"``, ``"sub_agent.web_searcher"``,
  ``"sub_agent.code_runner"``, ``"critic"``, ``"reviser"``, etc.
* ``step_index`` — 0-based within a turn. Used for sibling ordering
  when ``parent_trace_id`` is the same; for the root steps it just
  reflects insertion order.
* ``parent_trace_id`` — FK → ``agent_traces.id`` (nullable). Builds
  the tree for multi-agent flows where one step (e.g. a planner)
  spawns several sub-steps (the agents it dispatches).
* ``payload`` — JSONB, schema-by-convention. Steps decide what they
  need to capture: ``{prompt, response, model}`` for an LLM step;
  ``{tool_name, tool_args, tool_result}`` for a tool call;
  ``{confidence, decision, rationale}`` for a critic, etc. Keep
  payloads under ~64KB; persist large blobs (retrieved chunks,
  long transcripts) in their own table and reference by ID.
* ``duration_ms`` — wall-clock ms for the step.
* ``status`` — ``"ok" | "error"``. Mirrors ``llm_calls.status`` but
  with a smaller vocabulary because traces don't model rate-limits
  or budget exhaustion — those live on the cost meter.
* ``created_at`` — tz-aware, server default ``now()``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin

# Status literals — exported so callers don't sprinkle string
# literals across the codebase.
TRACE_STATUS_OK = "ok"
TRACE_STATUS_ERROR = "error"


class AgentTrace(IdMixin, Base):
    """One row per step in an agentic workflow — see module docstring."""

    __tablename__ = "agent_traces"
    __table_args__ = (
        # "Recent activity for this user" — the per-user view.
        Index(
            "ix_agent_traces_user_created",
            "user_id",
            "created_at",
        ),
        # "Recent activity for this feature" — the per-feature view.
        Index(
            "ix_agent_traces_feature_created",
            "feature",
            "created_at",
        ),
        # "Find every step that came out of this LLM call" — the
        # drill-down from the LLM cost row into the agent tree.
        Index(
            "ix_agent_traces_parent_call_id",
            "parent_call_id",
        ),
    )

    parent_call_id: Mapped[str | None] = mapped_column(
        # FK so we can drill down from a metered LLM call into its
        # agent-trace tree. ``ondelete="SET NULL"`` because we never
        # delete ``llm_calls`` rows in normal operation, but if an
        # operator ever does (e.g. a manual cleanup of error spikes),
        # we'd rather keep the trace history than cascade away the
        # forensic trail.
        ForeignKey("llm_calls.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=False
    )
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    parent_trace_id: Mapped[str | None] = mapped_column(
        # Self-referential FK for the tree. ``ondelete="CASCADE"`` so
        # if we ever do prune a top-level trace (TTL, GDPR, etc.) its
        # whole subtree goes with it — preserving an orphaned child
        # would leak data that we just promised to forget.
        ForeignKey("agent_traces.id", ondelete="CASCADE"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "AgentTrace",
    "TRACE_STATUS_ERROR",
    "TRACE_STATUS_OK",
]
