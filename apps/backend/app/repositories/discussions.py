from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.discussion import Discussion, DiscussionReply


async def list_for_course(
    db: AsyncSession, *, course_id: str, limit: int = 50, offset: int = 0
) -> list[tuple[Discussion, int, datetime]]:
    """List threads with reply count + last-activity timestamp.

    Last activity is ``max(thread.updated_at, latest reply.created_at)``
    so a thread that gets a fresh reply bubbles to the top in the
    default ordering.
    """
    last_reply_subq = (
        select(
            DiscussionReply.discussion_id.label("did"),
            func.max(DiscussionReply.created_at).label("last_reply_at"),
            func.count(DiscussionReply.id).label("reply_count"),
        )
        .where(DiscussionReply.deleted_at.is_(None))
        .group_by(DiscussionReply.discussion_id)
        .subquery()
    )
    last_activity = func.greatest(
        Discussion.updated_at,
        func.coalesce(last_reply_subq.c.last_reply_at, Discussion.updated_at),
    ).label("last_activity_at")
    stmt = (
        select(
            Discussion,
            func.coalesce(last_reply_subq.c.reply_count, 0).label("reply_count"),
            last_activity,
        )
        .outerjoin(last_reply_subq, last_reply_subq.c.did == Discussion.id)
        .where(Discussion.course_id == course_id, Discussion.deleted_at.is_(None))
        .options(selectinload(Discussion.author))
        .order_by(last_activity.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    # `reply_count` is wrapped in func.coalesce(..., 0) above so `rc` is
    # never None; the cast keeps the tuple's int contract regardless of
    # whether the driver returns int or Decimal.
    return [(d, int(rc), la) for d, rc, la in res.all()]


async def count_for_course(db: AsyncSession, *, course_id: str) -> int:
    stmt = select(func.count(Discussion.id)).where(
        Discussion.course_id == course_id, Discussion.deleted_at.is_(None)
    )
    return int((await db.execute(stmt)).scalar_one())


async def get(db: AsyncSession, discussion_id: str) -> Discussion | None:
    res = await db.execute(
        select(Discussion)
        .options(
            selectinload(Discussion.author),
            selectinload(Discussion.replies).selectinload(DiscussionReply.author),
        )
        .where(Discussion.id == discussion_id, Discussion.deleted_at.is_(None))
    )
    return res.scalar_one_or_none()


async def get_reply(db: AsyncSession, reply_id: str) -> DiscussionReply | None:
    res = await db.execute(
        select(DiscussionReply).where(
            DiscussionReply.id == reply_id, DiscussionReply.deleted_at.is_(None)
        )
    )
    return res.scalar_one_or_none()
