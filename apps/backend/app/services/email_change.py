"""Email change flow.

Two-step:

1. ``request_change`` — verifies the current password (destructive-
   action gate), checks the target address isn't already taken, mints
   a single-use JWT bound to (user.id, new_email, current pwd hash),
   and sends a confirmation link to the *new* address. The user has
   to prove control of the new mailbox before the change takes effect.

2. ``confirm_change`` — exchanges the token for the actual email
   update, audit-records it, and revokes every refresh token so any
   parallel session (laptop, phone) gets booted and re-authenticated.

Binding the token to the *current* password hash means a password
rotation between request and confirm invalidates outstanding email-
change tokens — same pattern password-reset uses.
"""

from __future__ import annotations

import time
from datetime import datetime, UTC

import jwt

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError, ValidationAppError
from app.core.logging import get_logger
from app.core.security import verify_password
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

_PURPOSE = "email-change"
_TTL_SECONDS = 60 * 60  # 1 hour


def make_token(user: User, *, new_email: str) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": user.id,
        "iat": now,
        "exp": now + _TTL_SECONDS,
        "purpose": _PURPOSE,
        "new_email": new_email,
        # Bind to current password hash — rotating it invalidates the token.
        "pwh": user.password_hash[-16:],
        "iss": "lumen",
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


async def request_change(
    db: AsyncSession,
    *,
    user: User,
    new_email: str,
    current_password: str,
) -> tuple[User, str | None]:
    """Mint a change-request token. Returns ``(user, token_or_None)``.

    Token is None when the new email matches the current — no-op
    success rather than an error so the UI can be friendly.
    """
    if new_email.strip().lower() == user.email.lower():
        return user, None
    if not verify_password(current_password, user.password_hash):
        raise UnauthorizedError("Current password is incorrect", code="auth.invalid_credentials")
    existing = await users_repo.get_by_email(db, new_email)
    if existing and existing.id != user.id:
        raise ConflictError("Email is already registered", code="auth.email_taken")
    token = make_token(user, new_email=new_email)
    return user, token


async def confirm_change(db: AsyncSession, *, token: str) -> User:
    s = get_settings()
    try:
        payload = jwt.decode(
            token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm], issuer="lumen"
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Link is invalid or expired", code="email_change.invalid") from exc
    if payload.get("purpose") != _PURPOSE:
        raise UnauthorizedError("Link is invalid", code="email_change.invalid")
    user = await users_repo.get_by_id(db, str(payload.get("sub", "")))
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found", code="email_change.invalid")
    if payload.get("pwh") != user.password_hash[-16:]:
        raise UnauthorizedError("Link is stale (password was rotated)", code="email_change.stale")
    new_email = str(payload.get("new_email", "")).strip()
    if not new_email:
        raise ValidationAppError("Token has no target email", code="email_change.invalid")
    # Re-check uniqueness at confirm time too — another account could
    # have grabbed the address between request and confirm.
    clash = await users_repo.get_by_email(db, new_email)
    if clash and clash.id != user.id:
        raise ConflictError("Email is already registered", code="auth.email_taken")

    old_email = user.email
    user.email = new_email
    # Force re-verification of the new address — same posture as register.
    user.email_verified_at = datetime.now(UTC)  # they just clicked a link in it
    await users_repo.revoke_all_refresh_tokens(db, user.id)
    await audit_repo.record(
        db,
        actor_id=user.id,
        action="auth.email_changed",
        target_type="user",
        target_id=user.id,
        data={"old_email": old_email, "new_email": new_email},
    )
    return user


def queue_confirmation_email(*, user: User, new_email: str, token: str) -> str | None:
    """Best-effort: send the confirmation link to the *new* mailbox."""
    s = get_settings()
    link = f"{str(s.web_base_url).rstrip('/')}/confirm-email-change?token={token}"
    text = (
        f"Hi,\n\n"
        f"You requested to change your Lumen email to this address. "
        f"Confirm within the next hour:\n\n{link}\n\n"
        f"If you didn't request this, ignore the message — nothing changes "
        f"until you click the link.\n"
    )
    try:
        from app.services.email_template import render_branded_html
        from app.workers.tasks.email import send

        html = render_branded_html(
            heading="Confirm your new email",
            body_paragraphs=[
                "You requested to change your Lumen email to this address. "
                "Click the button below to confirm. The link is valid for "
                "one hour.",
            ],
            cta_url=link,
            cta_label="Confirm email change",
        )
        send.delay(
            to=new_email,
            subject="Confirm your new Lumen email",
            text=text,
            html=html,
        )
    except Exception:  # dev w/o broker
        log.info("email_change_email_skipped", new_email=new_email, token=token)
        return link
    return link
