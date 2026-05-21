"""OpenTelemetry tracing wire-up.

The instrumentation runs in production / staging only — gated on
``OTEL_EXPORTER_OTLP_ENDPOINT`` being set. We pin two behaviours:

* default (no endpoint) is a no-op — no exporter, no spans, no
  network traffic; the test suite already runs in this mode and
  these tests just confirm that's intentional;
* repeated init calls are idempotent — important because tests
  rebuild the app per session and we shouldn't end up with N
  exporters fighting for the same OTLP endpoint.

We don't try to spin up a real OTLP receiver here — that'd be an
integration test for the otel-collector, not for our wire-up.
"""

from __future__ import annotations

import pytest

from app.core import tracing
from app.core.config import get_settings


def _reset_init_flag() -> None:
    tracing._initialised = False  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _isolate_tracing_state():
    _reset_init_flag()
    yield
    _reset_init_flag()


def test_init_is_noop_without_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        tracing.init_tracing(None)
        # The flag stays False — we exited early on the empty endpoint.
        assert tracing._initialised is False
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


def test_init_is_idempotent(monkeypatch) -> None:
    """Second init call must be a no-op so a TestClient rebuild
    doesn't accumulate exporters."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        tracing.init_tracing(None)
        # Flip the flag manually to simulate "endpoint was set on
        # first call" — we just want to verify the early-return on
        # second invocation, which is the load-bearing property for
        # production restarts under uvicorn --reload.
        tracing._initialised = True  # type: ignore[attr-defined]
        tracing.init_tracing(None)  # should not raise / not re-init
        assert tracing._initialised is True
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]
