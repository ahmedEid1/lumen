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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defense-in-depth response headers.

    The API serves JSON to the Next.js frontend; HTML rendering only
    happens at ``/docs`` (Swagger UI) and the empty ``/``. None of
    these legitimately need to be framed, sniffed, or referer-leaked
    to third parties, so the defaults are tight. In production we
    also pin HSTS — Caddy in front of us also sets it, but defense in
    depth keeps the API safe behind any future direct-exposure mistake.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        # Don't clobber a header the inner handler set deliberately.
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Restrict powerful browser features the API never needs. A
        # learner's browser opens the frontend, not the API, so locking
        # these down on the API origin is purely defensive.
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        if get_settings().is_prod:
            # 2-year HSTS with preload — once a browser sees this, it
            # refuses HTTP for the duration. Only meaningful in prod
            # because dev uses plain HTTP on localhost.
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
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
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    from app.core.ratelimit import limiter

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

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded):
        rid = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
        return ORJSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limited",
                    "message": "Too many requests — please slow down",
                    "details": {"limit": str(exc.detail)},
                    "request_id": rid,
                }
            },
            headers={"Retry-After": "60"},
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
    app.add_middleware(SecurityHeadersMiddleware)
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
