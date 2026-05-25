"""Agent-tracer service — write + read ``agent_traces`` rows.

Lumen v2 Phase H7. The substrate I2 (multi-agent tutor) and I3
(self-critique authoring) call into. One write helper, two read
helpers; no business logic — just persistence + retrieval.

Why a service module (and not the model directly):

1. **SAVEPOINT isolation.** Trace writes mirror H1's
   ``llm_call_log.call_logged`` pattern — a transient DB hiccup
   while persisting a trace step MUST NOT roll back the agent's
   actual work. ``record_step`` wraps the INSERT in
   ``session.begin_nested()`` and swallows ``SQLAlchemyError``,
   logging at WARNING. The trace might be lost; the user's
   experience is not.

2. **Single read path.** The dashboard's drill-down ("show me the
   trace tree for this LLM call") is one query the API can issue
   without re-deriving the join graph each time. ``list_traces_for_call``
   centralises it.

3. **Open-ended payloads.** Callers pass an arbitrary ``dict`` as
   ``payload``. JSONB on the column side means we don't have to
   migrate the schema every time I2/I3 invents a new step kind
   with new fields.

The three public functions:

* :func:`record_step` — write one trace row. Returns the persisted
  ORM instance so callers can use ``trace.id`` as the
  ``parent_trace_id`` for the next step they record.
* :func:`list_traces_for_call` — every trace row whose
  ``parent_call_id`` matches the given LLM call id, ordered for
  in-place tree rendering (parents before children, siblings in
  ``step_index`` order).
* :func:`list_recent` — paginated list for the dashboard's
  top-level "recent activity" view.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agent_trace import TRACE_STATUS_OK, AgentTrace

log = get_logger(__name__)


async def record_step(
    db: AsyncSession,
    *,
    user_id: str,
    feature: str,
    step: str,
    step_index: int,
    parent_trace_id: str | None = None,
    parent_call_id: str | None = None,
    payload: dict[str, Any] | None = None,
    duration_ms: int = 0,
    status: str = TRACE_STATUS_OK,
) -> AgentTrace | None:
    """Persist one ``agent_traces`` row. Best-effort.

    Wraps the INSERT in a SAVEPOINT so a transient DB error on the
    trace doesn't roll back the caller's outer transaction. On
    failure we log at WARNING and return ``None``; on success we
    return the persisted ORM row.

    Returning ``None`` on failure (rather than raising) is the same
    trade-off H1's ``_persist_row`` makes for the cost meter — a
    passive observability path must never fail the user-facing
    request it's observing. Callers that need the returned ``id``
    to parent a follow-up step should handle the ``None`` case
    explicitly (typically by passing ``parent_trace_id=None`` and
    letting the next step root a fresh subtree).

    ``payload`` defaults to ``{}`` rather than ``None`` so the
    JSONB column never holds NULL — the dashboard reads payloads
    unconditionally, and an empty object is cheaper to handle than
    a nullable check on every render.
    """
    try:
        async with db.begin_nested():
            row = AgentTrace(
                user_id=user_id,
                feature=feature,
                step=step,
                step_index=step_index,
                parent_trace_id=parent_trace_id,
                parent_call_id=parent_call_id,
                payload=payload or {},
                duration_ms=duration_ms,
                status=status,
            )
            db.add(row)
            # Flush inside the savepoint so a constraint error fires
            # here (and we catch + log it) rather than bubbling up
            # at the next outer-transaction operation.
            await db.flush()
            await db.refresh(row)
            return row
    except SQLAlchemyError:
        log.exception(
            "agent_trace_persist_failed",
            user_id=user_id,
            feature=feature,
            step=step,
            parent_call_id=parent_call_id,
            parent_trace_id=parent_trace_id,
        )
        return None


async def list_traces_for_call(db: AsyncSession, call_id: str) -> list[AgentTrace]:
    """Return every trace row tied to ``call_id`` — flat, in tree order.

    The list is ordered ``created_at ASC, step_index ASC`` so a
    naive in-order walk produces a stable tree rendering: rows are
    emitted in the same order their flow recorded them. The
    frontend builds the actual tree structure from
    ``parent_trace_id`` — we don't try to nest server-side because
    JSON tree shapes are awkward to type and the rows are tens, not
    thousands.
    """
    stmt = (
        select(AgentTrace)
        .where(AgentTrace.parent_call_id == call_id)
        .order_by(AgentTrace.created_at.asc(), AgentTrace.step_index.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_recent(
    db: AsyncSession,
    *,
    feature: str | None = None,
    user_id: str | None = None,
    limit: int = 50,
) -> list[AgentTrace]:
    """Recent trace rows, newest first. Filters compose with AND.

    The dashboard's "recent activity" view calls this with no
    filters; the per-feature drill calls it with ``feature=`` set.
    Capped at the call site (default 50) — neither index is large
    enough that a thousand-row scan would matter, but a small page
    keeps the JSON payload manageable for the browser.
    """
    stmt = select(AgentTrace).order_by(AgentTrace.created_at.desc()).limit(limit)
    if feature is not None:
        stmt = stmt.where(AgentTrace.feature == feature)
    if user_id is not None:
        stmt = stmt.where(AgentTrace.user_id == user_id)
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "list_recent",
    "list_traces_for_call",
    "record_step",
]
