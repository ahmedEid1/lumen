"""Authentication: register, login, refresh rotation, logout."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, ForbiddenError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import (
    TokenPair,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models.user import RefreshToken, Role, User
from app.repositories import audit as audit_repo
from app.repositories import users as users_repo
from app.services import password_hibp

if TYPE_CHECKING:
    from app.schemas.auth import LoginRequest, RegisterRequest

log = get_logger(__name__)

# Precomputed Argon2 hash of a value the user can never supply. ``verify_password``
# against it does the same CPU work as a real check but always returns False.
# We rely on this to flatten the login-latency side-channel that would
# otherwise leak whether an email is registered (a missing user would skip
# the hash and return ~10ms faster than a wrong password).
_DUMMY_HASH = hash_password("\x00 not-a-real-password \x00")


async def register(
    db: AsyncSession,
    payload: RegisterRequest,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> User:
    existing = await users_repo.get_by_email(db, str(payload.email))
    if existing:
        raise ConflictError("Email is already registered", code="auth.email_taken")
    # Reject passwords known to be breached *before* persisting the
    # account — the user can pick a fresh value without dirtying state.
    await password_hibp.assert_not_pwned(payload.password)
    user = await users_repo.create(
        db,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=Role.student,
    )
    await audit_repo.record(
        db,
        actor_id=user.id,
        action="auth.register",
        target_type="user",
        target_id=user.id,
        ip_address=ip,
        user_agent=user_agent,
    )
    return user


async def authenticate(
    db: AsyncSession,
    payload: LoginRequest,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    user = await users_repo.get_by_email(db, str(payload.email))
    if not user or not user.is_active:
        # Run a dummy verify so the wire-time latency for "no such email" and
        # "wrong password" is dominated by the same Argon2 work — denying an
        # attacker the timing side-channel that would otherwise reveal which
        # emails are registered.
        verify_password(payload.password, _DUMMY_HASH)
        raise UnauthorizedError("Invalid credentials", code="auth.invalid_credentials")
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise ForbiddenError("Account temporarily locked", code="auth.locked")

    if not verify_password(payload.password, user.password_hash):
        await users_repo.update_login_failure(db, user)
        raise UnauthorizedError("Invalid credentials", code="auth.invalid_credentials")

    await users_repo.update_login_success(db, user)
    tokens = await _issue_tokens(db, user, ip=ip, user_agent=user_agent)
    await audit_repo.record(db, actor_id=user.id, action="auth.login", ip_address=ip, user_agent=user_agent)
    return user, tokens


async def rotate_refresh(
    db: AsyncSession,
    presented: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    token_hash = hash_refresh_token(presented)
    stored = await users_repo.get_refresh_token(db, token_hash)
    if not stored:
        raise UnauthorizedError("Invalid refresh token", code="auth.refresh_invalid")
    if stored.revoked_at is not None:
        # Reuse detection — revoke all tokens for this user.
        await users_repo.revoke_all_refresh_tokens(db, stored.user_id)
        await audit_repo.record(db, actor_id=stored.user_id, action="auth.refresh_reuse", ip_address=ip, user_agent=user_agent)
        raise UnauthorizedError("Refresh token reuse detected", code="auth.refresh_reuse")
    if stored.expires_at < datetime.now(timezone.utc):
        raise UnauthorizedError("Refresh token expired", code="auth.refresh_expired")

    user = await users_repo.get_by_id(db, stored.user_id)
    if not user or not user.is_active:
        raise UnauthorizedError("Account is not active", code="auth.inactive")

    tokens, replacement = await _issue_tokens_returning(db, user, ip=ip, user_agent=user_agent)
    await users_repo.revoke_refresh_token(db, stored, replaced_by_id=replacement.id)
    return user, tokens


async def logout(db: AsyncSession, presented: str | None) -> None:
    if not presented:
        return
    token_hash = hash_refresh_token(presented)
    stored = await users_repo.get_refresh_token(db, token_hash)
    if stored and stored.revoked_at is None:
        await users_repo.revoke_refresh_token(db, stored)


async def _issue_tokens(
    db: AsyncSession, user: User, *, ip: str | None, user_agent: str | None
) -> TokenPair:
    pair, _ = await _issue_tokens_returning(db, user, ip=ip, user_agent=user_agent)
    return pair


async def _issue_tokens_returning(
    db: AsyncSession, user: User, *, ip: str | None, user_agent: str | None
) -> tuple[TokenPair, RefreshToken]:
    s = get_settings()
    access, exp = create_access_token(subject=user.id, role=user.role.value)
    raw, digest = new_refresh_token()
    rt_expires = datetime.now(timezone.utc) + timedelta(seconds=s.refresh_token_ttl_seconds)
    stored = await users_repo.add_refresh_token(
        db,
        user=user,
        token_hash=digest,
        expires_at=rt_expires,
        user_agent=user_agent,
        ip_address=ip,
    )
    pair = TokenPair(
        access_token=access,
        access_expires_at=exp,
        refresh_token=raw,
        refresh_expires_at=int(rt_expires.timestamp()),
    )
    return pair, stored
