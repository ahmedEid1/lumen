"""Health probes."""

from __future__ import annotations

from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DBSession
from app.core.config import get_settings

router = APIRouter()


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe")
async def ready(db: DBSession) -> Any:
    checks: dict[str, str] = {}
    overall = status.HTTP_200_OK

    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc.__class__.__name__}"
        overall = status.HTTP_503_SERVICE_UNAVAILABLE

    try:
        r = redis.Redis.from_url(get_settings().redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"
        overall = status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(status_code=overall, content={"status": "ok" if overall == 200 else "degraded", "checks": checks})
