"""User notifications."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError
from app.repositories import notifications as notifications_repo
from app.schemas.common import OkResponse
from app.schemas.notification import NotificationOut

router = APIRouter()


@router.get("", response_model=list[NotificationOut])
async def list_my(user: CurrentUser, db: DBSession) -> list[NotificationOut]:
    rows = await notifications_repo.list_for_user(db, user.id)
    return [NotificationOut.model_validate(n) for n in rows]


@router.post("/{notification_id}/read", response_model=OkResponse)
async def mark_read(notification_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    from app.models.notification import Notification

    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise NotFoundError("Notification not found", code="notification.not_found")
    await notifications_repo.mark_read(db, notification)
    return OkResponse()


@router.post("/read-all", response_model=dict)
async def mark_all_read(user: CurrentUser, db: DBSession) -> dict:
    """Mark every unread notification for the current user as read.

    Single round trip instead of N. Returns the count touched so the
    UI can update its badge without another GET.
    """
    touched = await notifications_repo.mark_all_read_for_user(db, user_id=user.id)
    return {"ok": True, "marked_read": touched}
