"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.deps import CurrentUser, DBSession, client_ip, user_agent
from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.schemas.auth import (
    EmailVerifyConfirm,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.common import OkResponse
from app.schemas.user import UserOut
from app.services import auth as auth_service
from app.services import email_verify as verify_service
from app.services import password_reset as reset_service

router = APIRouter()


def _set_auth_cookies(response: Response, *, access: str, refresh: str, access_exp: int, refresh_exp: int) -> None:
    is_prod = get_settings().is_prod
    response.set_cookie(
        key="__Host-access" if is_prod else "access",
        value=access,
        httponly=True,
        secure=is_prod,
        samesite="strict",
        path="/",
        max_age=max(access_exp - 0, 0),
    )
    response.set_cookie(
        key="__Host-refresh" if is_prod else "refresh",
        value=refresh,
        httponly=True,
        secure=is_prod,
        samesite="strict",
        path="/",
        max_age=max(refresh_exp - 0, 0),
    )


def _clear_auth_cookies(response: Response) -> None:
    is_prod = get_settings().is_prod
    for name in ("__Host-access", "__Host-refresh", "access", "refresh"):
        response.delete_cookie(name, path="/", secure=is_prod)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DBSession, request: Request) -> UserOut:
    user = await auth_service.register(db, payload, ip=client_ip(request), user_agent=user_agent(request))
    verify_service.queue_verification_email(user=user)
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: DBSession,
) -> TokenResponse:
    user, tokens = await auth_service.authenticate(
        db, payload, ip=client_ip(request), user_agent=user_agent(request)
    )
    _set_auth_cookies(
        response,
        access=tokens.access_token,
        refresh=tokens.refresh_token,
        access_exp=tokens.access_expires_at,
        refresh_exp=tokens.refresh_expires_at,
    )
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=get_settings().access_token_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    request: Request,
    db: DBSession,
    refresh_cookie: str | None = Cookie(default=None, alias="__Host-refresh"),
    legacy_cookie: str | None = Cookie(default=None, alias="refresh"),
) -> TokenResponse:
    presented = refresh_cookie or legacy_cookie
    if not presented:
        raise UnauthorizedError("Missing refresh token", code="auth.refresh_missing")
    user, tokens = await auth_service.rotate_refresh(
        db, presented, ip=client_ip(request), user_agent=user_agent(request)
    )
    _set_auth_cookies(
        response,
        access=tokens.access_token,
        refresh=tokens.refresh_token,
        access_exp=tokens.access_expires_at,
        refresh_exp=tokens.refresh_expires_at,
    )
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=get_settings().access_token_ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=OkResponse)
async def logout(
    response: Response,
    db: DBSession,
    refresh_cookie: str | None = Cookie(default=None, alias="__Host-refresh"),
    legacy_cookie: str | None = Cookie(default=None, alias="refresh"),
) -> OkResponse:
    await auth_service.logout(db, refresh_cookie or legacy_cookie)
    _clear_auth_cookies(response)
    return OkResponse()


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/password-reset/request", response_model=OkResponse)
async def password_reset_request(payload: PasswordResetRequest, db: DBSession) -> OkResponse:
    """Always returns ok to avoid leaking which emails exist."""
    user, token = await reset_service.request_reset(db, email=str(payload.email))
    if user and token:
        # In production this kicks off a Celery email task. In dev, log the link so it's visible
        # in the API container logs and in Mailpit once the worker is wired.
        try:
            from app.workers.tasks.email import send

            link = f"{get_settings().api_base_url}/reset-password?token={token}"
            send.delay(
                to=user.email,
                subject="Reset your Lumen password",
                text=f"Click the link to reset your password (valid 30 min):\n\n{link}\n",
            )
        except Exception:  # noqa: BLE001  - dev path without broker shouldn't 500 the API
            from app.core.logging import get_logger

            get_logger(__name__).info(
                "password_reset_email_skipped", email=user.email, token=token
            )
    return OkResponse()


@router.post("/password-reset/confirm", response_model=OkResponse)
async def password_reset_confirm(payload: PasswordResetConfirm, db: DBSession) -> OkResponse:
    await reset_service.confirm_reset(db, token=payload.token, new_password=payload.password)
    return OkResponse()


@router.post("/verify/request", response_model=OkResponse)
async def verify_request(user: CurrentUser) -> OkResponse:
    """Resend the email-verification link for the current user."""
    if user.email_verified_at is None:
        verify_service.queue_verification_email(user=user)
    return OkResponse()


@router.post("/verify/confirm", response_model=OkResponse)
async def verify_confirm(payload: EmailVerifyConfirm, db: DBSession) -> OkResponse:
    await verify_service.confirm(db, token=payload.token)
    return OkResponse()
