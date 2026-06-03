"""S7pre.5 — value-level redaction filter (ADR-0027 §7, R-U3 / FR-BYOK-24).

A last-stage structlog processor (after ``_redact``) plus an exception /
error-envelope scrubber that walks *values* (not just key names) and masks
any in-flight secret. The key-name-only ``_redact`` can't catch a decrypted
key that lands as a value in an arbitrary log field, exception arg, or
error-envelope ``details``.

This is the enumerated-sink contract per R-U3: a sentinel "key" is driven
through each sink and asserted absent. Sinks that don't exist yet (the
``llm_calls`` / ``agent_traces`` rows from S5) are noted as deferred to
S5.10 — this S7-pre task ships the wiring + the sinks that exist today
(structlog output, exception tracebacks, the error envelope).
"""

from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from app.core import logging as app_logging

SENTINEL = "sk-SENTINEL-byok-key-do-not-log-1234567890"


@pytest.fixture
def captured_logs():
    """Configure structlog to write JSON into a buffer + install value redaction."""
    buf = io.StringIO()
    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            app_logging.value_redaction_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
    yield buf
    structlog.reset_defaults()


def test_value_redaction_processor_exists():
    assert hasattr(app_logging, "value_redaction_processor")
    assert hasattr(app_logging, "install_value_redaction")
    assert hasattr(app_logging, "scrub_secrets")


def test_sentinel_redacted_in_structlog_value(captured_logs):
    log = structlog.get_logger()
    log.info("byok_dispatch", api_key=SENTINEL, note=f"key is {SENTINEL} here")
    out = captured_logs.getvalue()
    assert SENTINEL not in out
    assert "***" in out or "[redacted]" in out.lower()


def test_sentinel_redacted_nested_structures(captured_logs):
    log = structlog.get_logger()
    log.info(
        "nested",
        payload={"cred": {"key": SENTINEL}, "list": [SENTINEL, "ok"]},
    )
    out = captured_logs.getvalue()
    assert SENTINEL not in out


def test_known_prefix_keys_redacted(captured_logs):
    """Vendor key prefixes (sk-, sk-ant-, gsk_) are scrubbed even without the
    test sentinel registered."""
    log = structlog.get_logger()
    log.info(
        "providerkeys",
        a="sk-ant-api03-REALKEYMATERIALAAAAAAAAAAAAAAAAAAAAAAAAAA",
        b="gsk_REALGROQKEYMATERIALBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
    )
    out = captured_logs.getvalue()
    assert "REALKEYMATERIAL" not in out
    assert "REALGROQKEYMATERIAL" not in out


def test_scrub_secrets_string():
    redacted = app_logging.scrub_secrets(f"prefix {SENTINEL} suffix", extra=(SENTINEL,))
    assert SENTINEL not in redacted
    assert "prefix" in redacted and "suffix" in redacted


def test_scrub_secrets_recurses_containers():
    obj = {"k": SENTINEL, "nested": [{"deep": SENTINEL}]}
    redacted = app_logging.scrub_secrets(obj, extra=(SENTINEL,))
    flat = json.dumps(redacted)
    assert SENTINEL not in flat


def test_scrub_secrets_handles_exception_traceback():
    """An exception carrying the sentinel in its message is scrubbed."""
    try:
        raise ValueError(f"provider rejected key {SENTINEL}")
    except ValueError as exc:
        scrubbed = app_logging.scrub_secrets(str(exc), extra=(SENTINEL,))
        assert SENTINEL not in scrubbed


def test_error_envelope_details_scrubbed():
    """The error-envelope ``details`` dict scrubs a leaked secret value."""
    details = {"capability": "can_use_byok", "leaked": SENTINEL}
    scrubbed = app_logging.scrub_secrets(details, extra=(SENTINEL,))
    assert SENTINEL not in json.dumps(scrubbed)
    # Non-secret structure preserved.
    assert scrubbed["capability"] == "can_use_byok"


def test_install_value_redaction_idempotent():
    """install_value_redaction can be called repeatedly (API + worker boot)
    without raising or duplicating the processor unboundedly."""
    app_logging.configure_logging(level="INFO")
    app_logging.install_value_redaction()
    app_logging.install_value_redaction()  # second call (worker reuse) is safe
    log = structlog.get_logger()
    # Smoke: logging the sentinel after install does not raise.
    log.info("smoke", key=SENTINEL)


def test_deferred_sinks_documented():
    """S5.10 has now caught up: every previously-deferred sink is covered by
    the enumerated-sink completion test (test_byok_sink_completion.py), so the
    deferred set is empty and the covered set names the full contract."""
    assert app_logging.DEFERRED_REDACTION_SINKS == ()
    assert set(app_logging.REDACTION_SINKS_COVERED) >= {
        "llm_calls",
        "agent_traces",
        "celery_task_payloads",
        "me_export",
        "openapi_schema",
    }
