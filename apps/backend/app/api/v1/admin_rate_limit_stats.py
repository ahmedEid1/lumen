"""Admin-only rate-limit metrics surface (Phase H6).

Surfaces 429 counts in a shape the H7 observability dashboard can
consume: ``{endpoint: count}`` for the last hour by default, or for
any custom window via the ``since`` query param (epoch seconds).

The router lives in its own module so it can be registered by the
top-level API router without entangling with the existing admin
catalogue surface (``app.api.v1.admin``). The orchestrator (H6 owner
*not* the router file owner) hooks it into ``app/api/v1/router.py``.

Response shape::

    {
      "since": 1716340800.0,
      "window_seconds": 3600.0,
      "total": 42,
      "by_endpoint": {"/api/v1/auth/login": 30, "/api/v1/courses": 12}
    }
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import RequireAdmin
from app.core import rate_limit_metrics

router = APIRouter()


class RateLimitStatsOut(BaseModel):
    """Aggregate 429 counts within a rolling window.

    ``window_seconds`` is the gap between the resolved ``since`` cutoff
    and the response timestamp — handy for the dashboard so it doesn't
    have to compute it client-side. ``total`` is the sum of every value
    in ``by_endpoint`` so a Prometheus exporter on the next deploy can
    pin a single number without re-summing.
    """

    since: float = Field(description="Epoch seconds cutoff (inclusive lower bound)")
    window_seconds: float = Field(description="Width of the window in seconds")
    total: int = Field(description="Total 429s within the window")
    by_endpoint: dict[str, int] = Field(
        default_factory=dict,
        description="Per-endpoint count, keyed by FastAPI route path",
    )


@router.get("/rate-limit-stats", response_model=RateLimitStatsOut)
async def rate_limit_stats(
    _: RequireAdmin,
    since: float | None = Query(
        default=None,
        description=(
            "Epoch seconds. Omit for a 1-hour rolling window. Pass an "
            "older timestamp to widen the window (capped by the in-memory "
            "buffer size of 10k events)."
        ),
    ),
) -> RateLimitStatsOut:
    """Return per-endpoint 429 counts for the requested window.

    Read-only and best-effort: the buffer is process-local and resets
    on every redeploy, so a horizontal scale-out would split the
    counts across replicas. Documented in ``docs/security.md`` so the
    dashboard can disclose this in the UI.
    """
    cutoff = since if since is not None else time.time() - 3600.0
    by_endpoint = rate_limit_metrics.counts_since(cutoff)
    return RateLimitStatsOut(
        since=cutoff,
        window_seconds=max(time.time() - cutoff, 0.0),
        total=sum(by_endpoint.values()),
        by_endpoint=by_endpoint,
    )
