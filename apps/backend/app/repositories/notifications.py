from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationKind


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    kind: NotificationKind,
    title: str,
    body: str = "",
    data: dict[str, Any] | None = None,
) -> Notification:
    n = Notification(user_id=user_id, kind=kind, title=title, body=body, data=data or {})
    db.add(n)
    await db.flush()
    return n


async def list_for_user(db: AsyncSession, user_id: str, *, limit: int = 50) -> list[Notification]:
    res = await db.execute(
        select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc()).limit(limit)
    )
    return list(res.scalars().all())


async def mark_read(db: AsyncSession, notification: Notification) -> None:
    if not notification.read_at:
        notification.read_at = datetime.now(timezone.utc)
