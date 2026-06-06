"""Structured logging via structlog → JSON to stdout."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import (
    CallsiteParameter,
    CallsiteParameterAdder,
    JSONRenderer,
    StackInfoRenderer,
    TimeStamper,
    format_exc_info,
)

_REDACT_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "set-cookie",
    "cookie",
}


def _redact(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS and event_dict[key] is not None:
            event_dict[key] = "***"
    return event_dict


# ---------------------------------------------------------------------------
# S7-pre.5 — value-level redaction (ADR-0027 §7, R-U3 / FR-BYOK-24)
# ---------------------------------------------------------------------------
#
# ``_redact`` masks by *key name*. That cannot catch a decrypted provider key
# that lands as a *value* in an arbitrary log field, exception message, or
# error-envelope ``details``. The value-level filter below walks values,
# recursing into dicts/lists/tuples, and replaces any substring matching a
# known vendor-key prefix pattern OR a test-injected sentinel.
#
# This is defense-in-depth: the structural guarantee is that keys only ever
# live inside a ``SecretStr``-wrapped provider and are decrypted solely in
# ``byok.build_provider`` (S5). The enumerated-sink sentinel test is the
# tested contract.

_REDACTION_PLACEHOLDER = "***[redacted-secret]***"

# Vendor API-key shapes. Conservative on purpose — these match obvious key
# material without eating ordinary prose. Each captures a recognizable prefix
# followed by a run of key-charset bytes.
_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),  # Anthropic
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{8,}"),  # OpenAI project keys
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI / generic sk-
    re.compile(r"gsk_[A-Za-z0-9_\-]{16,}"),  # Groq
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
)

# The full enumerated-sink contract (R-U3 / FR-BYOK-24). At S7-pre these
# tables/rows did not exist yet; S5.10 now drives a sentinel BYOK key through
# every one and asserts absence (see test_byok_sink_completion.py). The set
# below is the *covered* contract.
REDACTION_SINKS_COVERED: tuple[str, ...] = (
    "llm_calls",
    "agent_traces",
    "retrieval_audits",
    "tutor_turn_jobs",
    "celery_task_payloads",
    "me_export",
    "openapi_schema",
    "structlog",
    "exception_traceback",
    "error_envelope",
    "admin_views",
)

# No sinks remain deferred: S5.10 covers the full set above. Retained (empty)
# so any importer of the S7-pre name keeps resolving.
DEFERRED_REDACTION_SINKS: tuple[str, ...] = ()


def _scrub_str(text: str, extra: tuple[str, ...]) -> str:
    for needle in extra:
        if needle:
            text = text.replace(needle, _REDACTION_PLACEHOLDER)
    for pat in _KEY_PATTERNS:
        text = pat.sub(_REDACTION_PLACEHOLDER, text)
    return text


def scrub_secrets(value: Any, *, extra: tuple[str, ...] = ()) -> Any:
    """Recursively redact secret material from ``value``.

    Walks strings, dicts, lists, tuples and sets. ``extra`` is a tuple of
    exact substrings to mask (the in-flight sentinel / known key bytes); the
    built-in vendor-prefix patterns always apply. Non-string scalars are
    returned untouched. Used by the structlog processor, the error-envelope
    scrubber, and (via ``install_value_redaction``) worker sinks.
    """
    if isinstance(value, str):
        return _scrub_str(value, extra)
    if isinstance(value, dict):
        return {k: scrub_secrets(v, extra=extra) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        scrubbed = [scrub_secrets(v, extra=extra) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    if isinstance(value, set):
        return {scrub_secrets(v, extra=extra) for v in value}
    return value


def value_redaction_processor(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Last-stage structlog processor: scrub secret values across the event.

    Registered AFTER ``_redact`` so key-name masking happens first (cheap)
    and this catches anything that slipped through as a value — including the
    rendered ``event`` message and any ``exception``/``exc_info`` text.
    """
    return scrub_secrets(event_dict)


def install_value_redaction() -> None:
    """Append the value-redaction processor to the active structlog config.

    Exported so the Celery worker (which configures its own logging at
    ``worker_process_init``) reuses the exact same filter (R-S1′f). Idempotent
    — calling it twice does not stack duplicate processors. If structlog has
    not been configured yet, this is a no-op (the API/worker call
    ``configure_logging`` first, which already installs the processor).
    """
    try:
        cfg = structlog.get_config()
    except Exception:  # pragma: no cover - structlog not configured yet
        return
    processors = list(cfg.get("processors", []))
    if value_redaction_processor in processors:
        return
    # Insert just before the final renderer so the renderer sees scrubbed
    # values. The renderer is conventionally the last entry.
    if processors:
        processors.insert(len(processors) - 1, value_redaction_processor)
    else:
        processors = [value_redaction_processor]
    structlog.configure(processors=processors)


def configure_logging(level: str = "INFO", *, json: bool = True, stderr: bool = False) -> None:
    """Install structlog as the project logger.

    Set ``stderr=True`` when stdout is reserved for a wire protocol —
    e.g. the MCP stdio transport, which requires that the only thing
    written to stdout be valid JSON-RPC frames. With ``stderr=True``
    both stdlib logging and structlog's ``PrintLoggerFactory`` route
    everything to ``sys.stderr``.
    """
    stream = sys.stderr if stderr else sys.stdout
    logging.basicConfig(
        format="%(message)s",
        stream=stream,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    shared_processors: list[Any] = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        # NB: ``add_logger_name`` requires a stdlib LoggerFactory (it
        # reads logger.name); we use PrintLoggerFactory below for
        # zero-config console output. CallsiteParameterAdder gives us
        # MODULE / FUNC_NAME / LINENO which is strictly more useful
        # than the logger-name field anyway, so dropping it costs
        # nothing.
        TimeStamper(fmt="iso", utc=True),
        CallsiteParameterAdder(
            parameters={
                CallsiteParameter.MODULE,
                CallsiteParameter.FUNC_NAME,
                CallsiteParameter.LINENO,
            }
        ),
        StackInfoRenderer(),
        format_exc_info,
        _redact,
        # S7-pre.5: value-level secret scrub, AFTER key-name redaction and
        # after exc_info is rendered to text so a leaked key in a traceback
        # is caught too (R-U3).
        value_redaction_processor,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            JSONRenderer() if json else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )

    # Quiet noisy libs by default.
    for noisy in ("uvicorn.access", "watchfiles.main", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
