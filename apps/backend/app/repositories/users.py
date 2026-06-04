from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken, Role, User


async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def count_active_admins(db: AsyncSession, *, excluding: str | None = None) -> int:
    """Count users who are an *active* admin (``role==admin AND is_active``).

    The last-admin invariant (FR-ADMIN-03) computes the count against the
    target's *prospective* new state: pass ``excluding=target.id`` to ask "how
    many active admins would remain if this user no longer counted?". A tombstone
    (``is_active=False``) is excluded automatically.
    """
    stmt = select(func.count(User.id)).where(User.role == Role.admin, User.is_active.is_(True))
    if excluding is not None:
        stmt = stmt.where(User.id != excluding)
    return int((await db.execute(stmt)).scalar_one())


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == email))
    return res.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    full_name: str,
    role: Role = Role.user,  # S1.8: default to the canonical `user` role
) -> User:
    user = User(email=email, password_hash=password_hash, full_name=full_name, role=role)
    db.add(user)
    await db.flush()
    return user


async def update_login_success(db: AsyncSession, user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    await db.flush()


async def update_login_failure(db: AsyncSession, user: User, *, lockout_threshold: int = 5) -> None:
    # failed_login_attempts is NOT NULL DEFAULT 0 (see User model), so plain
    # `+= 1` is safe — no need to guard against None on freshly-seeded rows.
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= lockout_threshold:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
    await db.flush()


async def add_refresh_token(
    db: AsyncSession,
    *,
    user: User,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None,
    ip_address: str | None,
) -> RefreshToken:
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        issued_at=datetime.now(UTC),
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(rt)
    await db.flush()
    return rt


async def get_refresh_token(db: AsyncSession, token_hash: str) -> RefreshToken | None:
    res = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    return res.scalar_one_or_none()


async def revoke_refresh_token(
    db: AsyncSession, token: RefreshToken, *, replaced_by_id: str | None = None
) -> None:
    token.revoked_at = datetime.now(UTC)
    token.replaced_by_id = replaced_by_id


async def revoke_all_refresh_tokens(db: AsyncSession, user_id: str) -> None:
    # Single bulk UPDATE instead of SELECT-then-N-writes. Only called from the
    # refresh-reuse detection path, which immediately raises after this so the
    # session's identity map doesn't need to see the revoked rows again.
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def purge_refresh_tokens(db: AsyncSession, user_id: str) -> None:
    """Hard-delete every refresh token for a user (ADR-0030 §D2 step 5).

    Account deletion is terminal: revocation alone leaves hashed rows; this
    removes the residue so no session material survives the tombstone. Used by
    ``account.delete_account`` after ``revoke_all_refresh_tokens``.
    """
    await db.execute(sa_delete(RefreshToken).where(RefreshToken.user_id == user_id))


async def mark_deleted(db: AsyncSession, user: User) -> None:
    """Set the ``deleted_at`` tombstone marker (ADR-0030 §D2 step 3).

    The single discriminator between a *suspended* account (``deleted_at IS
    NULL``) and a *deleted* one (``deleted_at IS NOT NULL``); both share
    ``is_active=False``.
    """
    user.deleted_at = datetime.now(UTC)
