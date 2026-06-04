"""Application exception hierarchy + FastAPI handlers."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, scrub_secrets

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


class TutorUserCapError(AppError):
    """L33 — the calling user has exhausted their per-user microcent
    reservation for the rolling window. Frontend renders the
    cost-cap closing CTA (L23) on this code."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "tutor.user_cap"


class TutorIpCapError(AppError):
    """L33 — the calling IP has exhausted its per-IP microcent
    reservation. Catches anonymous-burst abuse where many user
    accounts share one IP."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "tutor.ip_cap"


class TutorGlobalCapError(AppError):
    """L33 — the global daily microcent budget is exhausted. Kills
    the demo for the day so a runaway loop or coordinated abuse
    can't bankrupt the prod LLM key."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "tutor.global_cap"


class TutorConcurrencyLimitError(AppError):
    """L33 — the user already has `tutor_max_concurrent` streaming
    turns in flight. Returns 429 with a `Retry-After: 5` so the
    client can naturally back off."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "tutor.too_many_concurrent"


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


# ---------------------------------------------------------------------------
# S5 (BYOK) error codes — ADR-0027 §"Error codes". All map to the standard
# {error:{code,message,details,request_id}} envelope; ``details`` is scrubbed
# by the value-redaction filter (S5.10) as defense-in-depth.
# ---------------------------------------------------------------------------


class QuotaExceededError(AppError):
    """S5.8 — the pre-dispatch DB COUNT request/job quota is exhausted.

    Independent of dollars: a $0 BYOK call still counts (DR-16). A sentinel
    ``llm_calls`` row (``status="quota_exceeded"``) is persisted and the
    provider is never invoked. 429 so the client backs off; the tripped
    dimension is in ``details``. A quota-exhausted BYOK user is BLOCKED,
    not routed to the free platform model (ADR-0027 §4 item 6).
    """

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "llm.quota_exceeded"


class ByokBaseUrlForbiddenError(ValidationAppError):
    """Any URL-ish field on a credential payload (FR-BYOK-14). 422."""

    code = "byok.base_url_forbidden"


class ByokModelNotAllowedError(ValidationAppError):
    """Stored/requested model is not in the provider's curated allowlist. 422."""

    code = "byok.model_not_allowed"


class ByokProviderNotAllowedError(ValidationAppError):
    """Provider is not in the allowlisted registry. 422."""

    code = "byok.provider_not_allowed"


class ByokCredentialNotFoundError(NotFoundError):
    """No live credential for the (user, provider). 404."""

    code = "byok.credential_not_found"


class ByokValidateRateLimitedError(RateLimitedError):
    """Validate anti-oracle cap tripped (R-S4). 429."""

    code = "byok.validate_rate_limited"


class ByokMustStoreBeforeValidateError(AppError):
    """Cannot validate a key that was never stored (anti-oracle, R-S4). 412."""

    status_code = status.HTTP_412_PRECONDITION_FAILED
    code = "byok.must_store_before_validate"


class ByokCapabilityRevokedError(ForbiddenError):
    """can_use_byok denied (suspended user / flag off). 403."""

    code = "byok.capability_revoked"


class ByokModelUnavailableError(AppError):
    """Stored model drifted out of the allowlist (R-M11'). Surfaced as a
    one-time notice when falling back to platform; carries the notice code.
    """

    status_code = status.HTTP_409_CONFLICT
    code = "byok.model_unavailable"


class ByokProviderError(AppError):
    """BYOK dispatch failed and no platform fallback is permitted
    (``allow_platform_fallback=False``). Errors are REDACTED — no vendor
    headers/request-ids/raw bodies/key echo (ADR-0027 §4 item 3).
    """

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "tutor.byok_provider_error"


# ---------------------------------------------------------------------------
# S6 (admin/account-lifecycle) error codes — ADR-0030 §"Error codes" +
# FR-ADMIN-03 / FR-SUSP-04. All map to the standard envelope.
# ---------------------------------------------------------------------------


class LastAdminError(ValidationAppError):
    """FR-ADMIN-03 — the platform must always retain ≥1 active admin.

    422. Returned when revoking the admin role from the last active admin
    (``user.last_admin``); suspension reuses the same invariant via
    ``user.last_admin_active``.
    """

    code = "user.last_admin"


class AccountSuspendedError(UnauthorizedError):
    """ADR-0030 §D3 / FR-SUSP-04 — login/refresh on a *suspended* account
    (``is_active=False AND deleted_at IS NULL``). Distinct from the generic
    ``auth.invalid_credentials`` so the frontend can surface a precise message.
    """

    code = "auth.account_suspended"


class AccountDeletedError(UnauthorizedError):
    """ADR-0030 §D3 — login/refresh on a *tombstoned* account
    (``deleted_at IS NOT NULL``). Distinct from ``auth.account_suspended``.
    """

    code = "auth.account_deleted"


class AccountDeletedIrreversibleError(ValidationAppError):
    """ADR-0030 §D3 — admin reinstate refused on a tombstoned account. 422.

    A deleted account can never be reactivated through the suspension surface
    (legal erasure / restoration is offline-admin only).
    """

    code = "user.deleted_irreversible"


class AccessRevokedError(ForbiddenError):
    """ADR-0030 §D4 / R-S10 — cooperative-cancellation signal. 403.

    Raised by ``assert_account_active`` at streaming heartbeats and build/clone
    phase fences when the caller's account flipped to ``is_active=False`` (suspend
    or delete) mid-flight, so the in-flight job aborts instead of running to
    completion.
    """

    code = "account.access_revoked"


def _payload(
    code: str, message: str, *, details: dict[str, Any] | None, request_id: str | None
) -> dict[str, Any]:
    # S7-pre.5 (R-U3): defense-in-depth value-level scrub of the outbound
    # error envelope so a leaked secret can never escape via a 4xx/5xx body.
    # The structural guarantee is that secrets live only inside SecretStr
    # providers; this catches a stray value in ``message``/``details``.
    return {
        "error": {
            "code": code,
            "message": scrub_secrets(message),
            "details": scrub_secrets(details or {}),
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
