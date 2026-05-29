"""FastAPI app factory + uvicorn entrypoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit

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
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import install_handlers
from app.core.logging import configure_logging, get_logger
from app.core.prod_guards import assert_production_safe
from app.core.rate_limit_metrics import record_rate_limited
from app.core.ratelimit import limiter
from app.core.tracing import init_tracing
from app.db.base import dispose_engine

settings = get_settings()
configure_logging(
    level=settings.log_level, json=not settings.is_dev or settings.env.value == "production"
)
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
        # Strip server-software advertising. uvicorn sets ``Server:
        # uvicorn`` by default; auditors flag this as information
        # disclosure (helps attackers fingerprint a known-version stack).
        # MutableHeaders is case-insensitive on `__contains__` / `__delitem__`
        # but exposes no `pop`; the suppress guard covers the racy missing-key.
        if "server" in headers:
            with suppress(KeyError):
                del headers["server"]
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
        # CSP only on JSON responses. The Swagger UI at /docs is the
        # only HTML this service serves and it relies on inline
        # scripts + a CDN; a strict CSP would break it. JSON bodies
        # never render in a browser, so ``default-src 'none'`` is a
        # cheap belt-and-suspenders for the "what if someone tricks a
        # browser into treating our response as HTML" attack class.
        ct = headers.get("content-type", "")
        if ct.startswith("application/json"):
            headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
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


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """Origin-header CSRF guard for cookie-authenticated mutations.

    SameSite=strict on our auth cookies already blocks most browser
    CSRF (browsers won't send the cookie on a cross-site request) but
    it doesn't help if:

    * a same-site origin gets compromised (subdomain takeover);
    * a future cookie rotation accidentally weakens SameSite;
    * an older browser without modern SameSite support is in play.

    For mutating methods we therefore also require the request to
    carry an ``Origin`` (or fall back to ``Referer``) that matches one
    of the configured CORS origins — i.e. the same set the API has
    decided it's willing to talk to. Bearer-token clients (mobile,
    Postman, server-to-server) skip the check because they had to
    explicitly set the Authorization header to make the call in the
    first place — CSRF doesn't apply to them.
    """

    _MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def dispatch(self, request: Request, call_next):
        if request.method in self._MUTATING:
            # Bearer wins: if the request explicitly carries an
            # Authorization header, it's an API client (mobile, Postman,
            # server-to-server) and CSRF doesn't apply — the attacker
            # cannot set that header cross-origin. We check this BEFORE
            # the cookie check so a browser-cookie-and-bearer-both case
            # (e.g., post-login session that also kept the cookie) still
            # routes through the Bearer-trusted path.
            has_bearer = bool(request.headers.get("authorization"))
            has_cookie_auth = any(
                k in request.cookies
                for k in ("__Host-access", "__Host-refresh", "access", "refresh")
            )
            if has_cookie_auth and not has_bearer:
                allowed = {o.rstrip("/") for o in get_settings().cors_origins}
                origin = (request.headers.get("origin") or "").rstrip("/")
                if not origin:
                    # Some browsers omit Origin on same-origin POSTs; fall
                    # back to Referer's scheme://host[:port] in that case.
                    referer = request.headers.get("referer") or ""
                    if referer:
                        # Cheap scheme://host extraction — full URL parse
                        # isn't worth the cost on the hot path.
                        try:
                            parts = urlsplit(referer)
                            if parts.scheme and parts.netloc:
                                origin = f"{parts.scheme}://{parts.netloc}".rstrip("/")
                        except ValueError:
                            origin = ""
                if origin not in allowed:
                    return ORJSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "csrf.bad_origin",
                                "message": "Request origin is not trusted for cookie-authenticated mutations",
                                "details": {"origin": origin or None},
                                "request_id": getattr(request.state, "request_id", None),
                            }
                        },
                    )
        return await call_next(request)


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path = route.path if route else request.url.path
        try:
            http_requests_total.labels(request.method, path, str(response.status_code)).inc()
            http_request_duration_seconds.labels(request.method, path).observe(duration)
        except Exception as exc:
            # Don't let a broken Prometheus collector fail the request.
            log.debug("metrics_observe_failed", error=str(exc))
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
            request_id=getattr(request.state, "request_id", None),
        )
        return response


# ---------- CORS filter (H6) ----------


def _filter_prod_cors_origins(origins: list[str], *, is_prod: bool) -> list[str]:
    """Strip loopback / .test origins from the allowed list in production.

    In dev / test / staging we keep everything as-is so the test suite's
    ``http://testserver`` and the docker-compose ``http://web:3000``
    keep working. In production a stray ``http://localhost:3000`` in
    the env var would let any origin running on a developer's laptop
    talk to the live API once a browser is tricked into making the
    request — defense in depth on top of the cookie ``__Host-*`` prefix.

    Returns the filtered list; never mutates the input.
    """
    if not is_prod:
        return list(origins)
    keep: list[str] = []
    for raw in origins:
        o = (raw or "").strip().rstrip("/")
        if not o:
            continue
        lower = o.lower()
        # Substring match catches scheme + port + path variants:
        # http://localhost, https://127.0.0.1:8443, http://api.foo.test, …
        if any(host in lower for host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")):
            continue
        # The ``.test`` TLD is reserved for local development (RFC 2606)
        # and must never be a production origin. Match the *host* part
        # only so a real prod domain that happens to contain ``test``
        # in a path or query string survives.
        try:
            host = lower.split("://", 1)[1] if "://" in lower else lower
            host = host.split("/", 1)[0]
            host = host.rsplit(":", 1)[0]
            if host.endswith(".test"):
                continue
        except IndexError:
            continue
        keep.append(o)
    return keep


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.assert_production_ready()
    # H6 — extra production boot guards beyond the Settings-level checks:
    # noop LLM provider, short secrets, loopback DATABASE_URL, suspicious
    # OPENAI_API_BASE. The guard raises on hard problems and returns
    # soft warnings we route through structlog so the operator sees them
    # even when the boot succeeds.
    warnings = assert_production_safe(settings)
    for msg in warnings:
        log.warning("prod_guard_warning", message=msg)

    # L21-Sec — idempotent grandfather backstop. The migration ran on
    # deploy, but the deploy window (rolling restart of API containers)
    # is wide enough that a user can register between the migration
    # completing and the verification gate activating on every replica.
    # Re-running the COALESCE on boot covers that window. It's a no-op
    # in 99.9% of boots (every user already has the column set).
    try:
        await _grandfather_unverified_on_boot()
    except Exception as exc:  # pragma: no cover - boot-path safety net
        # Refuse to boot only on schema mismatch (Alembic must have
        # been run). Any other failure is logged and ignored so we
        # don't take the API down for a non-critical backstop.
        log.warning("l21sec_grandfather_boot_failed", error=str(exc))

    log.info("startup", env=settings.env.value, app=settings.app_name)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("shutdown")


async def _grandfather_unverified_on_boot() -> None:
    """Idempotent: any user that existed BEFORE the L21-Sec deploy
    cutoff whose email_verified_at is still NULL gets backfilled with
    their created_at. Mirrors the Alembic migration; needed because
    the deploy window between migration-complete and full-restart is
    wide enough for new registrations to slip through (plan-v7
    §V7-F9).

    **Codex rescue (post-redesign L21-Sec):** the cutoff is REQUIRED
    — without it, every API restart silently auto-verifies any user
    who registered after the deploy and hasn't clicked their email
    yet, defeating the whole point of the email-verification gate.
    Cutoff is `settings.l21sec_deploy_timestamp` (the L21-Sec deploy
    moment).

    Runs unconditionally; the WHERE clauses make it a no-op when no
    rows match.
    """
    from sqlalchemy import text

    from app.db.base import get_sessionmaker

    Session = get_sessionmaker()
    async with Session() as db:
        result = await db.execute(
            text(
                """
                UPDATE users
                SET email_verified_at = COALESCE(email_verified_at, created_at)
                WHERE email_verified_at IS NULL
                  AND created_at < :cutoff
                RETURNING id
                """
            ),
            {"cutoff": settings.l21sec_deploy_timestamp},
        )
        rows = result.fetchall()
        if rows:
            log.info(
                "l21sec_grandfather_boot",
                count=len(rows),
                cutoff=settings.l21sec_deploy_timestamp.isoformat(),
            )
        await db.commit()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0-rebuild",
        default_response_class=ORJSONResponse,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={"name": "Lumen", "url": "https://github.com/ahmedEid1/lumen"},
        license_info={"name": "MIT"},
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded):
        rid = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
        # H6 — feed the rate-limit-stats endpoint. Best-effort; a busted
        # counter must not turn a 429 into a 500.
        try:
            route = request.scope.get("route")
            path = route.path if route else request.url.path
            record_rate_limited(path)
        except Exception as e:  # pragma: no cover — counter is in-memory
            log.debug("rate_limit_metric_failed", error=str(e))
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

    # H6 — strip loopback / .test origins in production. Configured here
    # rather than in Settings so the filter only runs at app-build time
    # (not at every ``get_settings()`` call) and so tests can exercise
    # ``_filter_prod_cors_origins`` directly.
    allowed_origins = _filter_prod_cors_origins(settings.cors_origins, is_prod=settings.is_prod)
    if settings.is_prod and not allowed_origins:
        raise RuntimeError("Production CORS_ORIGINS must include at least one non-loopback origin")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFOriginMiddleware)
    app.add_middleware(AccessLogMiddleware)

    install_handlers(app)

    app.include_router(api_router)

    if settings.prometheus_enabled:

        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> PlainTextResponse:
            return PlainTextResponse(
                generate_latest(_registry).decode(), media_type=CONTENT_TYPE_LATEST
            )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": "1.0.0-rebuild", "docs": "/docs"}

    if settings.sentry_dsn:  # pragma: no cover - depends on env
        import sentry_sdk

        from app.core.sentry_scrubber import before_send

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            environment=settings.env.value,
            # L21-Sec — zero out tutor-namespace locals + request bodies
            # before the event ships. See app/core/sentry_scrubber.py.
            before_send=before_send,
        )

    # OpenTelemetry — opt-in via OTEL_EXPORTER_OTLP_ENDPOINT. No-op
    # when unset (dev / test / air-gapped).
    init_tracing(app)

    return app


app = create_app()
