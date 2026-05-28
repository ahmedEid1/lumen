"""Admin observability — agent traces + retrieval audits + Celery health.

Lumen v2 Phase H7. Three read-only endpoints powering the
``/admin/observability`` dashboard:

* ``GET /admin/observability/llm-calls/{call_id}/trace`` — the
  drill-down: one LLM call (prompt/response/cost/latency from
  ``llm_calls``) PLUS its agent-trace tree PLUS any linked
  retrieval audits. Returns a nested JSON structure ready for
  direct rendering — the frontend doesn't need to assemble the
  shape itself.

* ``GET /admin/observability/retrieval`` — recent retrieval-audit
  rows, filterable by ``since``, ``user_id``, ``limit``. The
  "Retrieval Quality" tab.

* ``GET /admin/observability/celery`` — best-effort Celery health:
  queue depth read directly off Redis (each Celery queue is a
  Redis list), plus the worker's reported active + scheduled
  tasks via ``celery.control.inspect()``. Falls back to
  ``"service offline"`` when Redis is down so the dashboard
  renders the degraded state instead of blowing up.

This router is registered in ``app/api/router.py`` under the
``/api/v1/admin`` prefix, so the paths above resolve to
``/api/v1/admin/observability/*``. ``AgentTrace`` and
``RetrievalAudit`` are exported from ``app/models/__init__.py`` so
Alembic autogenerate and the test conftest's ``create_all`` see them.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select

from app.api.deps import DBSession, RequireAdmin
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.agent_trace import AgentTrace
from app.models.llm_call import LLMCall
from app.models.retrieval_audit import RetrievalAudit
from app.services.agent_tracer import list_traces_for_call

log = get_logger(__name__)

router = APIRouter()


# ---------- DTOs ----------


class LLMCallSummary(BaseModel):
    """Slimmed-down ``LLMCall`` projection for the drill-down view.

    Same shape as ``admin_llm_calls.LLMCallOut`` — re-defined here
    so this router doesn't import a peer router's DTO (which would
    couple the two surfaces unnecessarily).
    """

    model_config = ConfigDict(from_attributes=True)

    call_id: str
    user_id: str
    feature: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_ms: int
    status: str
    error_kind: str | None
    created_at: datetime


class TraceStepOut(BaseModel):
    """One ``agent_traces`` row on the wire.

    ``payload`` is passed through as an open object — the dashboard
    chooses how to render based on ``step``.
    """

    model_config = ConfigDict(from_attributes=True)

    trace_id: str
    parent_trace_id: str | None
    parent_call_id: str | None
    step: str
    step_index: int
    payload: dict[str, Any]
    duration_ms: int
    status: str
    created_at: datetime


class RetrievalAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: str
    user_id: str
    feature: str
    query: str
    course_id: str | None
    chunks: list[dict[str, Any]]
    top_score: float | None
    created_at: datetime


class LLMCallTraceOut(BaseModel):
    """Drill-down payload: the LLM call + its agent-trace tree + audits.

    The ``traces`` list is flat but pre-sorted (``created_at ASC,
    step_index ASC``) so a naive walk produces a stable rendering;
    the frontend builds the tree off ``parent_trace_id``. ``audits``
    is included because a retrieval that triggered this LLM call
    typically wrote one row right before the call landed; we
    surface them in the same response to save a round-trip.
    """

    call: LLMCallSummary
    traces: list[TraceStepOut]
    audits: list[RetrievalAuditOut]


class CeleryQueueDepth(BaseModel):
    name: str
    depth: int


class CeleryHealthOut(BaseModel):
    redis_status: str
    queues: list[CeleryQueueDepth]
    active: dict[str, list[dict[str, Any]]] | None = None
    scheduled: dict[str, list[dict[str, Any]]] | None = None
    note: str | None = None


# ---------- Helpers ----------


def _llm_call_to_summary(row: LLMCall) -> LLMCallSummary:
    return LLMCallSummary(
        call_id=row.id,
        user_id=row.user_id,
        feature=row.feature,
        provider=row.provider,
        model=row.model,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        cost_usd=row.cost_usd,
        latency_ms=row.latency_ms,
        status=row.status,
        error_kind=row.error_kind,
        created_at=row.created_at,
    )


def _trace_to_out(row: AgentTrace) -> TraceStepOut:
    return TraceStepOut(
        trace_id=row.id,
        parent_trace_id=row.parent_trace_id,
        parent_call_id=row.parent_call_id,
        step=row.step,
        step_index=row.step_index,
        payload=row.payload or {},
        duration_ms=row.duration_ms,
        status=row.status,
        created_at=row.created_at,
    )


def _audit_to_out(row: RetrievalAudit) -> RetrievalAuditOut:
    return RetrievalAuditOut(
        audit_id=row.id,
        user_id=row.user_id,
        feature=row.feature,
        query=row.query,
        course_id=row.course_id,
        chunks=row.chunks or [],
        top_score=row.top_score,
        created_at=row.created_at,
    )


# ---------- Endpoints ----------


@router.get(
    "/observability/llm-calls/{call_id}/trace",
    response_model=LLMCallTraceOut,
)
async def get_llm_call_trace(
    call_id: str,
    _: RequireAdmin,
    db: DBSession,
) -> LLMCallTraceOut:
    """One LLM call + its trace tree + linked retrieval audits.

    Raises ``NotFoundError`` (404) when the call id doesn't exist.
    The trace + audit lists are empty when none have been recorded
    yet — that's the expected steady state until I2/I3 land and
    start writing.

    The audit lookup is heuristic: we pull any ``retrieval_audits``
    rows for the same ``user_id`` within ~60s before the LLM call's
    ``created_at``. The proper "this exact retrieval fed this exact
    call" link will be a column I2 adds on the trace row itself;
    until then the temporal heuristic is the right balance between
    "show the admin enough to debug" and "don't add a column the
    other agents haven't asked for yet".
    """
    call_row = (await db.execute(select(LLMCall).where(LLMCall.id == call_id))).scalar_one_or_none()
    if call_row is None:
        raise NotFoundError(
            f"LLM call {call_id} not found",
            code="observability.call_not_found",
            details={"call_id": call_id},
        )

    trace_rows = await list_traces_for_call(db, call_id)

    # Temporal heuristic for the audit link — see docstring. The
    # 60-second window is generous enough to cover a slow tutor
    # request (long retrieval + long LLM round-trip) without
    # pulling in unrelated activity from the same user.
    audit_window_start = call_row.created_at - timedelta(seconds=60)
    audit_rows = (
        (
            await db.execute(
                select(RetrievalAudit)
                .where(
                    RetrievalAudit.user_id == call_row.user_id,
                    RetrievalAudit.created_at >= audit_window_start,
                    RetrievalAudit.created_at <= call_row.created_at,
                )
                .order_by(desc(RetrievalAudit.created_at))
                .limit(5)
            )
        )
        .scalars()
        .all()
    )

    return LLMCallTraceOut(
        call=_llm_call_to_summary(call_row),
        traces=[_trace_to_out(r) for r in trace_rows],
        audits=[_audit_to_out(r) for r in audit_rows],
    )


@router.get(
    "/observability/retrieval",
    response_model=list[RetrievalAuditOut],
)
async def list_retrieval_audits(
    _: RequireAdmin,
    db: DBSession,
    since: datetime | None = Query(default=None),
    user_id: str | None = Query(default=None, max_length=64),
    feature: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RetrievalAuditOut]:
    """Recent retrieval-audit rows, newest first.

    All filters are optional and compose with AND. ``since`` is
    inclusive on the lower bound; the typical dashboard "last 24h"
    call passes ``since=now-24h``. ``user_id`` accepts the
    ``"__system__"`` sentinel for eval-suite traffic.
    """
    stmt = select(RetrievalAudit).order_by(desc(RetrievalAudit.created_at)).limit(limit)
    if since is not None:
        stmt = stmt.where(RetrievalAudit.created_at >= since)
    if user_id is not None:
        stmt = stmt.where(RetrievalAudit.user_id == user_id)
    if feature is not None:
        stmt = stmt.where(RetrievalAudit.feature == feature)
    rows = (await db.execute(stmt)).scalars().all()
    return [_audit_to_out(r) for r in rows]


# Celery queue names we surface depth for. Celery stores each queue
# as a Redis list keyed on the queue name (default routing puts
# every task on ``"celery"``); the celery_app declares additional
# queues via ``task_routes`` when we want to isolate slow work.
# Keep this list aligned with ``app/workers/celery_app.py`` —
# unknown queues just report depth 0.
_CELERY_QUEUE_NAMES: tuple[str, ...] = ("celery",)


@router.get(
    "/observability/celery",
    response_model=CeleryHealthOut,
)
async def get_celery_health(_: RequireAdmin) -> CeleryHealthOut:
    """Celery queue depths + recent worker introspection.

    Two data sources:

    1. **Queue depth** — direct ``LLEN`` against the broker Redis.
       Doesn't require a worker; reads the same key Celery uses to
       enqueue. Falls back to ``"service offline"`` cleanly when
       Redis is down.

    2. **Inspect** — Celery's ``control.inspect()`` round-trips
       through every live worker via the broker. When no worker is
       running (or the broker is down), ``ping()`` returns ``None``
       and we leave ``active`` / ``scheduled`` as ``None`` with a
       human-readable ``note``.

    Best-effort throughout — this endpoint is the dashboard's
    health-at-a-glance view, not a precise metric source. We hold
    the inspect timeout tight (0.5s) so a hung broker doesn't
    block the admin page render.
    """
    s = get_settings()

    queues: list[CeleryQueueDepth] = []
    redis_status = "ok"
    try:
        r = redis.Redis.from_url(s.celery_broker_url)
        for q in _CELERY_QUEUE_NAMES:
            try:
                depth = await r.llen(q)
            except Exception:
                depth = 0
            queues.append(CeleryQueueDepth(name=q, depth=int(depth)))
        await r.aclose()
    except Exception as exc:
        log.warning("celery_redis_unreachable", error=str(exc))
        redis_status = f"error: {exc.__class__.__name__}"
        # Still report the queues we know about with depth 0 so the
        # dashboard renders the row labels rather than an empty table.
        queues = [CeleryQueueDepth(name=q, depth=0) for q in _CELERY_QUEUE_NAMES]

    active: dict[str, list[dict[str, Any]]] | None = None
    scheduled: dict[str, list[dict[str, Any]]] | None = None
    note: str | None = None
    try:
        # Import inside the handler so a celery-less test
        # environment can still hit the endpoint (and get a clean
        # "no worker" response). The celery import itself is
        # cheap; we just want the failure mode to be a runtime
        # warning rather than an import-time crash.
        from app.workers.celery_app import celery as celery_app

        # The Celery ``control.inspect()`` API is *synchronous* and
        # uses Kombu under the hood, which opens its own AMQP/Redis
        # connection pool. The ``timeout`` kwarg only bounds how
        # long inspect waits for replies AFTER the broker round-trip
        # — it doesn't bound the connection-pool open / handshake /
        # reply-channel-drain phases, which under contention can sit
        # for tens of seconds. Calling it directly from this async
        # handler blocks the FastAPI event loop and (under pytest's
        # session-scoped asyncio loop, with a real worker
        # responding) deadlocks the entire suite.
        #
        # Wrap the sync work in ``asyncio.to_thread`` so the event
        # loop stays free, and hard-cap the whole probe with
        # ``asyncio.wait_for`` so a wedged broker or busy worker
        # surfaces as a "no worker reachable" note within 2 s
        # instead of holding the admin page render forever.
        def _probe_inspect() -> tuple[
            dict[str, list[dict[str, Any]]] | None,
            dict[str, list[dict[str, Any]]] | None,
            str | None,
        ]:
            inspect = celery_app.control.inspect(timeout=0.5)
            if inspect.ping() is None:
                return None, None, "no celery worker reachable"
            return (inspect.active() or {}), (inspect.scheduled() or {}), None

        active, scheduled, note = await asyncio.wait_for(
            asyncio.to_thread(_probe_inspect), timeout=2.0
        )
    except TimeoutError:
        note = "celery inspect probe timed out"
    except Exception as exc:
        log.warning("celery_inspect_failed", error=str(exc))
        note = f"inspect unavailable: {exc.__class__.__name__}"

    return CeleryHealthOut(
        redis_status=redis_status,
        queues=queues,
        active=active,
        scheduled=scheduled,
        note=note,
    )


# Orchestrator follow-up: register this router in
# ``apps/backend/app/api/router.py`` under the existing admin
# prefix, e.g.:
#
#     from app.api.v1 import admin_observability
#     api_router.include_router(
#         admin_observability.router,
#         prefix="/admin",
#         tags=["admin"],
#     )
#
# Also add ``AgentTrace`` and ``RetrievalAudit`` to
# ``apps/backend/app/models/__init__.py`` so Alembic autogenerate
# and the test conftest's ``create_all`` pick the models up.
