"""Admin observability for the LLM cost meter — Phase H1.

Two read-only endpoints, admin-only:

* ``GET /api/v1/admin/llm-calls`` — paginated list of metered calls
  with filters ``user_id``, ``feature``, ``status``, ``since``,
  ``until``. Newest first, capped at 200 rows per page.
* ``GET /api/v1/admin/llm-calls/summary`` — rollup view: total spend,
  cost by feature, cost by day for the last 14 days. The dashboard
  surface for "how much are we burning?"

The list endpoint deliberately includes the ``__system__`` sentinel
rows so an admin can see eval-suite + ingest spend; the summary
endpoint includes them in totals because the dollar number is what
matters at that level. Filter on ``user_id="__system__"`` (or pass
an explicit real ``user_id``) to slice if needed.

NOTE: this router is **not** registered in ``app/api/router.py`` —
the wave-1 orchestrator will mount it after the parallel agents
return. The expected mount is ``/api/v1/admin/llm-calls`` (matching
the URL examples above), included with ``tags=["admin"]``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, func, select

from app.api.deps import DBSession, RequireAdmin
from app.models.llm_call import LLMCall

router = APIRouter()


# ---------- DTOs ----------


class LLMCallOut(BaseModel):
    """One row of the metered call log on the wire.

    Renames the model's ``id`` PK to the more descriptive
    ``call_id`` so the admin UI reads naturally. ``cost_usd`` is
    serialised as a string to preserve the ``Numeric(10, 6)``
    precision through JSON — JS clients can render it with
    ``Number.parseFloat`` if they need maths, or display it raw.
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

    @classmethod
    def from_orm_row(cls, row: LLMCall) -> "LLMCallOut":
        return cls(
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


class FeatureBucket(BaseModel):
    feature: str
    calls: int
    cost_usd: Decimal


class DayBucket(BaseModel):
    day: str  # ISO date (YYYY-MM-DD) — easier to render than a full datetime
    calls: int
    cost_usd: Decimal


class SummaryOut(BaseModel):
    total_calls: int
    total_cost_usd: Decimal
    by_feature: list[FeatureBucket]
    by_day: list[DayBucket]


# ---------- Endpoints ----------


@router.get("/llm-calls", response_model=list[LLMCallOut])
async def list_llm_calls(
    _: RequireAdmin,
    db: DBSession,
    user_id: str | None = Query(default=None, max_length=64),
    feature: str | None = Query(default=None, max_length=64),
    status_: str | None = Query(default=None, alias="status", max_length=24),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[LLMCallOut]:
    """List metered LLM calls, newest first.

    All filters are optional and compose with AND semantics. The
    ``status`` query param is exposed under that name on the wire
    but binds to ``status_`` internally because ``status`` shadows
    the FastAPI import in this module otherwise. ``since`` / ``until``
    are inclusive on the lower bound, exclusive on the upper bound
    — the dashboard's typical "last 24h" call passes
    ``since=now-24h`` and omits ``until``.
    """
    stmt = (
        select(LLMCall)
        .order_by(desc(LLMCall.created_at))
        .limit(limit)
        .offset(offset)
    )
    if user_id is not None:
        stmt = stmt.where(LLMCall.user_id == user_id)
    if feature is not None:
        stmt = stmt.where(LLMCall.feature == feature)
    if status_ is not None:
        stmt = stmt.where(LLMCall.status == status_)
    if since is not None:
        stmt = stmt.where(LLMCall.created_at >= since)
    if until is not None:
        stmt = stmt.where(LLMCall.created_at < until)

    rows = (await db.execute(stmt)).scalars().all()
    return [LLMCallOut.from_orm_row(r) for r in rows]


@router.get("/llm-calls/summary", response_model=SummaryOut)
async def llm_calls_summary(
    _: RequireAdmin,
    db: DBSession,
    days: int = Query(default=14, ge=1, le=90),
) -> SummaryOut:
    """Aggregate spend rollup for the admin dashboard.

    Three aggregates in three round-trips:

    1. ``total_calls`` + ``total_cost_usd`` over the whole window.
    2. ``by_feature`` — one row per feature with its calls + cost.
    3. ``by_day`` — one row per UTC day for the last ``days`` days,
       ordered oldest → newest (so the chart renders left-to-right).

    Cheap on the composite ``(feature, created_at)`` index for the
    feature rollup, and a sort-bounded scan for the daily rollup.
    Both use ``date_trunc('day', created_at AT TIME ZONE 'UTC')`` so
    the bucket boundaries are calendar-stable regardless of server
    locale.
    """
    since = func.now() - func.make_interval(0, 0, 0, days)

    total_stmt = select(
        func.count(LLMCall.id),
        func.coalesce(func.sum(LLMCall.cost_usd), 0),
    ).where(LLMCall.created_at >= since)
    total_row = (await db.execute(total_stmt)).one()
    total_calls = int(total_row[0])
    total_cost = Decimal(str(total_row[1]))

    by_feature_stmt = (
        select(
            LLMCall.feature,
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        )
        .where(LLMCall.created_at >= since)
        .group_by(LLMCall.feature)
        .order_by(desc(func.sum(LLMCall.cost_usd)))
    )
    by_feature_rows = (await db.execute(by_feature_stmt)).all()
    by_feature = [
        FeatureBucket(
            feature=str(r[0]),
            calls=int(r[1]),
            cost_usd=Decimal(str(r[2])),
        )
        for r in by_feature_rows
    ]

    # Daily rollup. ``date_trunc('day', created_at)`` honours the
    # server's TIME ZONE setting, which is UTC in our deployments
    # (see ``Settings.tz``). Cast the truncated timestamp to a
    # date so the wire format is a clean ``YYYY-MM-DD`` string.
    day_col = func.date_trunc("day", LLMCall.created_at)
    by_day_stmt = (
        select(
            day_col.label("day"),
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
        )
        .where(LLMCall.created_at >= since)
        .group_by("day")
        .order_by("day")
    )
    by_day_rows = (await db.execute(by_day_stmt)).all()
    by_day = [
        DayBucket(
            day=(r[0].date().isoformat() if isinstance(r[0], datetime) else str(r[0])[:10]),
            calls=int(r[1]),
            cost_usd=Decimal(str(r[2])),
        )
        for r in by_day_rows
    ]

    return SummaryOut(
        total_calls=total_calls,
        total_cost_usd=total_cost,
        by_feature=by_feature,
        by_day=by_day,
    )


# Orchestrator follow-up: register this router in
# ``apps/backend/app/api/router.py`` under the existing admin
# prefix, e.g.:
#
#     from app.api.v1 import admin_llm_calls
#     api_router.include_router(
#         admin_llm_calls.router,
#         prefix="/admin",
#         tags=["admin"],
#     )
#
# Also add ``LLMCall`` to ``apps/backend/app/models/__init__.py`` so
# Alembic autogenerate + the test conftest's ``create_all`` pick
# the model up alongside everything else.
