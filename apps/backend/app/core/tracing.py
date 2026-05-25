"""OpenTelemetry tracing wire-up.

Opt-in via ``OTEL_EXPORTER_OTLP_ENDPOINT``. When empty (the default
in dev / test) tracing is a no-op — no spans created, zero overhead.
When set, we install:

* a TracerProvider with ``service.name`` from settings;
* an OTLP/HTTP span exporter pointing at the configured endpoint;
* auto-instrumentation for FastAPI, SQLAlchemy, and Redis (covers
  ~all the I/O we issue).

Init is idempotent — if called twice (e.g., by a test harness) the
second call is a no-op so we don't end up with duplicate exporters.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_initialised = False


def init_tracing(app=None) -> None:
    """Install OTLP exporter + auto-instrumentation if configured.

    ``app`` is the FastAPI instance; required when we want the
    FastAPI-specific instrumentation (route names in spans, request
    headers as attributes). Pass None to skip the FastAPI hook (e.g.
    in worker processes that only run Celery).
    """
    global _initialised
    if _initialised:
        return
    s = get_settings()
    endpoint = (s.otel_exporter_otlp_endpoint or "").strip()
    if not endpoint:
        log.debug("tracing_disabled", reason="no_endpoint")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        log.warning("tracing_import_failed", error=str(exc))
        return

    resource = Resource.create(
        {
            "service.name": s.otel_service_name,
            "deployment.environment": s.env.value,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    # SQLAlchemy + Redis are framework-level — instrumenting them
    # once captures every query / Redis op the API issues, including
    # those inside Celery workers when this is imported there.
    try:
        SQLAlchemyInstrumentor().instrument()
    except Exception as exc:  # already-instrumented is fine
        log.debug("sqlalchemy_instrument_skipped", error=str(exc))
    try:
        RedisInstrumentor().instrument()
    except Exception as exc:
        log.debug("redis_instrument_skipped", error=str(exc))

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                # Don't span the metrics scrape — it's the loudest
                # endpoint and traces of "Prometheus pulled metrics"
                # add noise without signal.
                excluded_urls="/metrics,/",
            )
        except Exception as exc:
            log.debug("fastapi_instrument_skipped", error=str(exc))

    _initialised = True
    log.info("tracing_enabled", endpoint=endpoint, service=s.otel_service_name)
