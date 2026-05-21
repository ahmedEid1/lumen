from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage


async def add_message(
    db: AsyncSession, *, course_id: str, author_id: str, body: str
) -> ChatMessage:
    msg = ChatMessage(course_id=course_id, author_id=author_id, body=body)
    db.add(msg)
    await db.flush()
    return msg


async def get_with_author(db: AsyncSession, message_id: str) -> ChatMessage | None:
    res = await db.execute(
        select(ChatMessage).options(selectinload(ChatMessage.author)).where(ChatMessage.id == message_id)
    )
    return res.scalar_one_or_none()


async def history(
    db: AsyncSession, *, course_id: str, before_id: str | None = None, limit: int = 50
) -> list[ChatMessage]:
    anchor = await db.get(ChatMessage, before_id) if before_id else None
    stmt = (
        select(ChatMessage)
        .options(selectinload(ChatMessage.author))
        .where(ChatMessage.course_id == course_id, ChatMessage.deleted_at.is_(None))
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
    )
    if anchor is not None:
        stmt = stmt.where(ChatMessage.created_at < anchor.created_at)
    res = await db.execute(stmt)
    return list(res.scalars().all())
