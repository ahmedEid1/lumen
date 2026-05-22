"""OpenLLMetry (Traceloop) initialisation — gated on an env flag.

Lumen v2 Phase H7. Traceloop's `traceloop-sdk` package auto-
instruments the Anthropic and OpenAI Python clients, emitting one
OTel span per LLM call with the prompt, response, token counts,
and the model name baked in as span attributes. Plugged in here so
every LLM round-trip already going through H1's metered
``call_logged`` *also* emits a richer OTel span — no call-site
changes needed.

The existing :mod:`app.core.tracing` module sets up the OTel
TracerProvider + the FastAPI / SQLAlchemy / Redis auto-
instrumentation; this module is the LLM-specific layer on top of
that. We deliberately keep them separate:

* :mod:`app.core.tracing` is always-on when ``OTEL_EXPORTER_OTLP_ENDPOINT``
  is set — it's the framework layer that every request needs.
* :mod:`app.core.otel` is gated by a separate ``OBSERVABILITY_ENABLED``
  flag so test runs (which have no OTLP collector) skip it cleanly,
  and so an operator can keep framework spans while turning off the
  prompt/response capture (which can carry sensitive content) for a
  compliance-sensitive deployment.

The Traceloop SDK reads the OTLP endpoint from the same env vars
the rest of the OTel toolchain uses
(``OTEL_EXPORTER_OTLP_ENDPOINT``), so we don't need to thread it
through manually.

This file is in the coverage omit list (``pyproject.toml``) — it's
a thin SDK-init shim with no testable branches, and its side
effects (network export of spans) are exercised in the
container-level smoke test, not unit tests.
"""

from __future__ import annotations

import os

from app.core.logging import get_logger

log = get_logger(__name__)

_initialised = False


def configure_otel() -> None:
    """Initialise Traceloop's OpenLLMetry SDK if the flag is on.

    No-op when ``OBSERVABILITY_ENABLED`` is anything other than
    ``"true"`` (case-insensitive). No-op on import error either —
    a deployment that doesn't install ``traceloop-sdk`` (slim
    image, test container) shouldn't crash on boot.

    Idempotent: calling twice (e.g. once from API startup, once
    from a worker import) is safe — the second call is a no-op.
    """
    global _initialised
    if _initialised:
        return
    if (os.environ.get("OBSERVABILITY_ENABLED") or "").strip().lower() != "true":
        log.debug("openllmetry_disabled", reason="flag_off")
        return

    try:
        # Import inside the function so a missing dep (test
        # containers without traceloop-sdk pulled in) doesn't crash
        # the API at module import time — the framework-level OTel
        # in app.core.tracing is the always-on path.
        from traceloop.sdk import Traceloop  # type: ignore[import-untyped]
    except ImportError as exc:
        log.warning("openllmetry_import_failed", error=str(exc))
        return

    try:
        # ``disable_batch=False`` keeps the default batched span
        # exporter (cheaper network-wise than per-span flushing).
        # The SDK reads OTLP endpoint + headers + service name from
        # the standard OTEL_* env vars we already set in
        # docker-compose / k8s manifests.
        Traceloop.init(
            app_name=os.environ.get("OTEL_SERVICE_NAME", "lumen-api"),
            disable_batch=False,
        )
    except Exception as exc:  # pragma: no cover - depends on SDK internals
        log.warning("openllmetry_init_failed", error=str(exc))
        return

    _initialised = True
    log.info("openllmetry_enabled")


__all__ = ["configure_otel"]
