"""Authentication: register, login, refresh rotation, logout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AccountDeletedError,
    AccountSuspendedError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)
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
from app.services import notifications as notifications_service
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
        # S1.8: new signups default to the canonical `user` role (every active
        # user can author + learn; admin is granted explicitly).
        role=Role.user,
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


def _raise_inactive(user: User) -> None:
    """ADR-0030 §D3 — surface the precise inactive-account code.

    Suspended (``is_active=False AND deleted_at IS NULL``) →
    ``auth.account_suspended``; tombstoned (``deleted_at IS NOT NULL``) →
    ``auth.account_deleted``. Both are 401 (``UnauthorizedError`` subclasses),
    replacing the generic ``auth.inactive``. Called ONLY after a successful
    password verify, so it never leaks whether an arbitrary email is suspended to
    a caller who doesn't hold the credential.
    """
    if user.deleted_at is not None:
        raise AccountDeletedError("This account has been deleted", code="auth.account_deleted")
    raise AccountSuspendedError("Your account has been suspended", code="auth.account_suspended")


async def authenticate(
    db: AsyncSession,
    payload: LoginRequest,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    user = await users_repo.get_by_email(db, str(payload.email))
    if not user:
        # Run a dummy verify so the wire-time latency for "no such email" and
        # "wrong password" is dominated by the same Argon2 work — denying an
        # attacker the timing side-channel that would otherwise reveal which
        # emails are registered.
        verify_password(payload.password, _DUMMY_HASH)
        raise UnauthorizedError("Invalid credentials", code="auth.invalid_credentials")
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise ForbiddenError("Account temporarily locked", code="auth.locked")

    if not verify_password(payload.password, user.password_hash):
        await users_repo.update_login_failure(db, user)
        raise UnauthorizedError("Invalid credentials", code="auth.invalid_credentials")

    # Password is correct — only now do we disclose suspended/deleted (ADR-0030
    # §D3). Branching before the verify would leak account-state to an attacker
    # who doesn't hold the credential; branching after keeps the existence-hide.
    if not user.is_active:
        _raise_inactive(user)

    await users_repo.update_login_success(db, user)
    tokens, _ = await _issue_tokens_returning(db, user, ip=ip, user_agent=user_agent)
    await audit_repo.record(
        db, actor_id=user.id, action="auth.login", ip_address=ip, user_agent=user_agent
    )
    return user, tokens


async def rotate_refresh(
    db: AsyncSession,
    presented: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    now = datetime.now(UTC)
    token_hash = hash_refresh_token(presented)
    stored = await users_repo.get_refresh_token(db, token_hash)
    if not stored:
        raise UnauthorizedError("Invalid refresh token", code="auth.refresh_invalid")
    if stored.revoked_at is not None:
        # Reuse detection — revoke all tokens for this user.
        await users_repo.revoke_all_refresh_tokens(db, stored.user_id)
        await audit_repo.record(
            db,
            actor_id=stored.user_id,
            action="auth.refresh_reuse",
            ip_address=ip,
            user_agent=user_agent,
        )
        # H6 — also fire an admin notification so an operator notices
        # the alarm without having to grep the audit log. The helper is
        # best-effort: a notification write failure must not poison the
        # auth path (we still want to raise the 401 below). Wrapped in
        # a broad except as defense-in-depth on top of the per-admin
        # handling inside ``notify_admins`` itself.
        try:
            owner = await users_repo.get_by_id(db, stored.user_id)
            who = owner.email if owner is not None else stored.user_id
            await notifications_service.notify_admins(
                db,
                kind="security.refresh_reuse",
                title=f"Refresh-token reuse detected for user {who}",
                body=(
                    "Chain revoked. Reused token created at "
                    f"{stored.issued_at.isoformat()}, last used "
                    f"{stored.revoked_at.isoformat() if stored.revoked_at else 'unknown'}. "
                    f"Source IP: {ip or 'unknown'}."
                ),
                data={
                    "user_id": stored.user_id,
                    "user_email": owner.email if owner is not None else None,
                    "refresh_token_id": stored.id,
                    "issued_at": stored.issued_at.isoformat(),
                    "revoked_at": stored.revoked_at.isoformat() if stored.revoked_at else None,
                    "ip": ip,
                    "user_agent": user_agent,
                },
            )
        except Exception as exc:  # pragma: no cover — defense in depth
            log.warning("refresh_reuse_alarm_failed", error=str(exc), user_id=stored.user_id)
        # H6 — the chain revocation, audit row, and admin notifications
        # above all live in the request's SQLAlchemy session. Without
        # this commit, the UnauthorizedError raise below propagates to
        # the FastAPI exception handler which then unwinds through
        # ``get_db``'s ``except: await session.rollback()`` clause —
        # reverting every effect of the reuse branch. Commit explicitly
        # so the security state changes (token revocation, alarm row)
        # persist even though we're returning an error response. A
        # second commit in ``get_db`` would be a no-op (no active
        # transaction), and the rollback path turns into a no-op too.
        try:
            await db.commit()
        except Exception as exc:  # pragma: no cover — extremely rare
            log.warning("refresh_reuse_commit_failed", error=str(exc), user_id=stored.user_id)
        raise UnauthorizedError("Refresh token reuse detected", code="auth.refresh_reuse")
    if stored.expires_at < now:
        raise UnauthorizedError("Refresh token expired", code="auth.refresh_expired")

    user = await users_repo.get_by_id(db, stored.user_id)
    if not user:
        raise UnauthorizedError("Account is not active", code="auth.inactive")
    if not user.is_active:
        # The caller proved possession of a live refresh token, so disclosing
        # suspended-vs-deleted is safe here (ADR-0030 §D3). Replaces the generic
        # auth.inactive with the precise code the frontend renders.
        _raise_inactive(user)

    tokens, replacement = await _issue_tokens_returning(db, user, ip=ip, user_agent=user_agent)
    await users_repo.revoke_refresh_token(db, stored, replaced_by_id=replacement.id)
    return user, tokens


async def logout(db: AsyncSession, presented: str | None) -> None:
    if not presented:
        return
    stored = await users_repo.get_refresh_token(db, hash_refresh_token(presented))
    if stored and stored.revoked_at is None:
        await users_repo.revoke_refresh_token(db, stored)


async def _issue_tokens_returning(
    db: AsyncSession, user: User, *, ip: str | None, user_agent: str | None
) -> tuple[TokenPair, RefreshToken]:
    settings = get_settings()
    # str() normalises Role (StrEnum) whether the column hands back enum or str.
    access, exp = create_access_token(subject=user.id, role=str(user.role))
    raw, digest = new_refresh_token()
    rt_expires = datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_seconds)
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
