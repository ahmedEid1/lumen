"""Email verification: stateless signed token, single-use via email_verified_at."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import jwt

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.logging import get_logger
from app.models.user import User
from app.repositories import audit as audit_repo
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

_PURPOSE = "email-verify"
_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def make_token(user: User) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": user.id,
        "iat": now,
        "exp": now + _TTL_SECONDS,
        "purpose": _PURPOSE,
        # Bind to current email so changing it invalidates outstanding tokens.
        "email": user.email,
        "iss": "lumen",
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


async def confirm(db: AsyncSession, *, token: str) -> User:
    s = get_settings()
    try:
        payload = jwt.decode(
            token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm], issuer="lumen"
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Verification link is invalid or expired", code="verify.invalid") from exc
    if payload.get("purpose") != _PURPOSE:
        raise UnauthorizedError("Verification link is invalid", code="verify.invalid")

    from app.repositories import users as users_repo

    user = await users_repo.get_by_id(db, str(payload.get("sub", "")))
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found", code="verify.invalid")
    if payload.get("email") != user.email:
        raise UnauthorizedError("Verification link is stale", code="verify.stale")

    if user.email_verified_at is not None:
        # Already verified — idempotent success rather than an error.
        return user

    user.email_verified_at = datetime.now(timezone.utc)
    await audit_repo.record(db, actor_id=user.id, action="auth.email_verified")
    return user


def queue_verification_email(*, user: User) -> str | None:
    """Best-effort: dispatch the verification email via Celery; returns the link or None."""
    token = make_token(user)
    s = get_settings()
    # web_base_url, not api_base_url — the verification page is a Next.js
    # route, the FastAPI host has no /verify-email handler.
    link = f"{str(s.web_base_url).rstrip('/')}/verify-email?token={token}"
    text = (
        f"Hi {user.full_name or ''},\n\n"
        f"Confirm your email by clicking the link (valid 24 h):\n\n{link}\n"
    )
    try:
        from app.services.email_template import render_branded_html
        from app.workers.tasks.email import send

        html = render_branded_html(
            heading="Confirm your email",
            body_paragraphs=[
                f"Hi {user.full_name or 'there'}, welcome to Lumen!",
                "Click the button below to confirm this is your address. The "
                "link is valid for 24 hours.",
            ],
            cta_url=link,
            cta_label="Confirm email",
        )
        send.delay(
            to=user.email,
            subject="Verify your Lumen email",
            text=text,
            html=html,
        )
    except Exception:  # noqa: BLE001 — broker may be down in dev
        log.info("verify_email_skipped", email=user.email, token=token)
        return link
    return link
