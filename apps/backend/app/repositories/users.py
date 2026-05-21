from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken, Role, User


async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    res = await db.execute(select(User).where(User.email == email))
    return res.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    full_name: str,
    role: Role = Role.student,
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
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
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
    now = datetime.now(UTC)
    res = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    )
    for tok in res.scalars().all():
        tok.revoked_at = now
