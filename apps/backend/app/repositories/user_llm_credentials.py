"""Async data access for BYOK credentials — no HTTP, no decrypt (S5.7).

The repo returns ORM rows. It NEVER decrypts ``enc_blob`` (decryption lives
solely in ``app.services.byok.build_provider``) and never serializes an
``enc_*`` field into a DTO.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_llm_credential import UserLLMCredential


def _live(stmt):
    return stmt.where(UserLLMCredential.deleted_at.is_(None))


async def get_by_id(db: AsyncSession, credential_id: str) -> UserLLMCredential | None:
    """Fetch a live credential by id (soft-deleted rows return ``None``)."""
    res = await db.execute(
        _live(select(UserLLMCredential).where(UserLLMCredential.id == credential_id))
    )
    return res.scalar_one_or_none()


async def get_active_for_user(db: AsyncSession, user_id: str) -> UserLLMCredential | None:
    """The user's single active+enabled live credential, if any."""
    res = await db.execute(
        _live(
            select(UserLLMCredential).where(
                UserLLMCredential.user_id == user_id,
                UserLLMCredential.is_active.is_(True),
            )
        )
    )
    return res.scalar_one_or_none()


async def get_for_user_provider(
    db: AsyncSession, user_id: str, provider: str
) -> UserLLMCredential | None:
    """The user's live credential for a given provider, if any."""
    res = await db.execute(
        _live(
            select(UserLLMCredential).where(
                UserLLMCredential.user_id == user_id,
                UserLLMCredential.provider == provider,
            )
        )
    )
    return res.scalar_one_or_none()


async def list_for_user(db: AsyncSession, user_id: str) -> list[UserLLMCredential]:
    """All live credentials for a user (masked at the schema edge)."""
    res = await db.execute(
        _live(
            select(UserLLMCredential)
            .where(UserLLMCredential.user_id == user_id)
            .order_by(UserLLMCredential.created_at.desc())
        )
    )
    return list(res.scalars().all())


async def soft_delete(db: AsyncSession, credential: UserLLMCredential) -> None:
    """Mark a credential deleted + clear its active flag (resolution → platform)."""
    credential.deleted_at = datetime.now(UTC)
    credential.is_active = False
    await db.flush()
