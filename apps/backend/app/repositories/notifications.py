from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
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
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def mark_read(db: AsyncSession, notification: Notification) -> None:
    if not notification.read_at:
        notification.read_at = datetime.now(UTC)


async def mark_all_read_for_user(db: AsyncSession, *, user_id: str) -> int:
    """Set read_at on every currently-unread notification owned by user.

    Uses a single UPDATE so it's O(1) round-trips regardless of how many
    notifications the learner has accumulated. Returns the rowcount so
    the caller (and the UI badge) can react without a follow-up GET.
    """
    res = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    return int(res.rowcount or 0)
