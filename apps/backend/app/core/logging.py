"""Structured logging via structlog → JSON to stdout."""

from __future__ import annotations

import logging
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


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    """Install structlog as the project logger."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
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
            parameters={CallsiteParameter.MODULE, CallsiteParameter.FUNC_NAME, CallsiteParameter.LINENO}
        ),
        StackInfoRenderer(),
        format_exc_info,
        _redact,
    ]

    structlog.configure(
        processors=[*shared_processors, JSONRenderer() if json else structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Quiet noisy libs by default.
    for noisy in ("uvicorn.access", "watchfiles.main", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()
