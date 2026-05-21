"""Password reset: stateless signed tokens, single-use via JWT jti + denylist."""

from __future__ import annotations

import time

import jwt

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

_PURPOSE = "pw-reset"


def make_token(user: User) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": user.id,
        "iat": now,
        "exp": now + s.password_reset_ttl_seconds,
        "purpose": _PURPOSE,
        # Bind the token to the current password hash: rotating it invalidates outstanding tokens.
        "pwh": user.password_hash[-16:],
        "iss": "lumen",
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm], issuer="lumen")


async def request_reset(db: AsyncSession, *, email: str) -> tuple[User | None, str | None]:
    user = await users_repo.get_by_email(db, email)
    if not user or not user.is_active:
        return None, None
    token = make_token(user)
    return user, token


async def confirm_reset(db: AsyncSession, *, token: str, new_password: str) -> User:
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Reset link is invalid or expired", code="auth.reset_invalid") from exc
    if payload.get("purpose") != _PURPOSE:
        raise UnauthorizedError("Reset link is invalid", code="auth.reset_invalid")
    user = await users_repo.get_by_id(db, str(payload.get("sub", "")))
    if not user or not user.is_active:
        raise UnauthorizedError("Account not found", code="auth.reset_invalid")
    if payload.get("pwh") != user.password_hash[-16:]:
        # Token was issued against a different password hash → already consumed or rotated.
        raise UnauthorizedError("Reset link already used", code="auth.reset_used")

    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    await users_repo.revoke_all_refresh_tokens(db, user.id)
    await audit_repo.record(db, actor_id=user.id, action="auth.password_reset")
    return user
