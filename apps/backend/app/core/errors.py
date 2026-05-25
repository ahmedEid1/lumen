"""Application exception hierarchy + FastAPI handlers."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)


class AppError(Exception):
    """Base class for all domain/application errors that map to HTTP responses."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "error"

    def __init__(
        self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class BudgetExceededError(AppError):
    """Raised when a user has burned through their 24h LLM budget.

    Lumen v2 Phase H1. The cost-meter wrapper
    (``app.services.llm_call_log.call_logged``) sums ``cost_usd``
    over the rolling 24h window for the caller; if that sum is
    already above ``settings.llm_user_budget_24h_usd``, the next
    call short-circuits with this error (and an ``llm_calls`` row
    is still persisted with ``status="budget_exceeded"`` so the
    admin observability surface sees the spike).

    We surface a 429 rather than a 402 because the limit is a
    rate-shaped guard against runaway loops, not a paywall — the
    same handler that emits ``Retry-After`` for rate-limit
    responses can treat budget exhaustion as "come back later".
    """

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "llm.budget_exceeded"


def _payload(
    code: str, message: str, *, details: dict[str, Any] | None, request_id: str | None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str | None:
    rid = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
    if rid:
        return rid
    rid = uuid.uuid4().hex
    request.state.request_id = rid
    return rid


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(
        request: Request, exc: AppError
    ) -> JSONResponse:  # pragma: no cover - thin shim
        rid = _request_id(request)
        log.warning(
            "app_error", code=exc.code, message=exc.message, details=exc.details, request_id=rid
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, details=exc.details, request_id=rid),
            headers={"X-Request-ID": rid or ""},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = _request_id(request)
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(code, str(exc.detail), details=None, request_id=rid),
            headers={"X-Request-ID": rid or ""},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = _request_id(request)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_payload(
                "validation_error",
                "Request validation failed",
                details={"errors": jsonable_encoder(exc.errors())},
                request_id=rid,
            ),
            headers={"X-Request-ID": rid or ""},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = _request_id(request)
        log.exception("unhandled_exception", request_id=rid)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_payload(
                "internal_error", "Internal server error", details=None, request_id=rid
            ),
            headers={"X-Request-ID": rid or ""},
        )
