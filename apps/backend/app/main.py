"""FastAPI app factory + uvicorn entrypoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse, PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import install_handlers
from app.core.logging import configure_logging, get_logger
from app.db.base import dispose_engine

settings = get_settings()
configure_logging(level=settings.log_level, json=not settings.is_dev or settings.env.value == "production")
log = get_logger(__name__)


# ---------- metrics ----------

_registry = CollectorRegistry()
http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests",
    ("method", "path", "status"),
    registry=_registry,
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Request duration",
    ("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=_registry,
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path  # type: ignore[union-attr]
        try:
            http_requests_total.labels(request.method, path, str(response.status_code)).inc()
            http_request_duration_seconds.labels(request.method, path).observe(duration)
        except Exception:  # noqa: BLE001
            pass
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
            request_id=getattr(request.state, "request_id", None),
        )
        return response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.assert_production_ready()
    log.info("startup", env=settings.env.value, app=settings.app_name)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        default_response_class=ORJSONResponse,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={"name": "Lumen", "url": "https://github.com/ahmedEid1/E-Learning-Platform"},
        license_info={"name": "MIT"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)

    install_handlers(app)

    app.include_router(api_router)

    if settings.prometheus_enabled:
        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> PlainTextResponse:
            return PlainTextResponse(generate_latest(_registry).decode(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": "1.0.0", "docs": "/docs"}

    if settings.sentry_dsn:  # pragma: no cover - depends on env
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1, environment=settings.env.value)

    return app


app = create_app()
