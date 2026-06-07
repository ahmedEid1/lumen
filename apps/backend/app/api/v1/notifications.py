"""User notifications.

Route order matters: every literal path (``/prefs``, ``/unread-count``,
``/inbox``, ``/clear``, ``/read-all``) is declared before the
``/{notification_id}`` parametrized routes so FastAPI never captures a
literal segment as an id.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DBSession
from app.core.errors import NotFoundError
from app.repositories import notifications as notifications_repo
from app.schemas.common import Cursor, OkResponse
from app.schemas.notification import (
    ClearRequest,
    ClearResult,
    MarkAllReadResult,
    NotificationOut,
    UnreadCountOut,
)
from app.schemas.notification_prefs import (
    NotificationPrefs,
    NotificationPrefsUpdate,
)
from app.services import notification_prefs as prefs_service

router = APIRouter()


@router.get("/prefs", response_model=NotificationPrefs)
async def get_my_prefs(user: CurrentUser, db: DBSession) -> NotificationPrefs:
    """Materialised dispatch map for the current user (Phase D4).

    Every :class:`NotificationKind` key is present in the response —
    kinds the user has never adjusted come back as the default
    (``in_app``) so the prefs UI can render a complete form from a
    single round-trip.
    """
    return NotificationPrefs(prefs=prefs_service.get_prefs(user))


@router.put("/prefs", response_model=NotificationPrefs)
async def update_my_prefs(
    payload: NotificationPrefsUpdate, user: CurrentUser, db: DBSession
) -> NotificationPrefs:
    """Partial update — only kinds in the payload are touched."""
    merged = await prefs_service.update_prefs(db, user=user, prefs=payload.prefs)
    return NotificationPrefs(prefs=merged)


@router.get("", response_model=list[NotificationOut])
async def list_my(user: CurrentUser, db: DBSession) -> list[NotificationOut]:
    """Bare newest-50 array — the bell popover's contract, kept unchanged.

    History past 50 (and unread filtering) lives on ``GET /inbox``; this
    endpoint deliberately stays cap-and-shape frozen so existing consumers
    of the generated client keep typechecking.
    """
    rows = await notifications_repo.list_for_user(db, user.id)
    return [NotificationOut.model_validate(n) for n in rows]


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(user: CurrentUser, db: DBSession) -> UnreadCountOut:
    """One COUNT for the badge — accurate past the bare list's 50-row cap."""
    n = await notifications_repo.unread_count_for_user(db, user_id=user.id)
    return UnreadCountOut(unread_count=n)


@router.get("/inbox", response_model=Cursor[NotificationOut])
async def inbox(
    user: CurrentUser,
    db: DBSession,
    cursor: str | None = Query(
        default=None,
        max_length=21,
        description="Cursor: the id of the last notification from the previous page.",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    unread: bool = Query(default=False, description="Only unread rows."),
) -> Cursor[NotificationOut]:
    """Cursor-paginated history — reaches everything the newest-50 bell can't."""
    rows, next_cursor = await notifications_repo.list_page_for_user(
        db, user_id=user.id, cursor=cursor, limit=limit, unread_only=unread
    )
    return Cursor[NotificationOut](
        items=[NotificationOut.model_validate(n) for n in rows],
        next_cursor=next_cursor,
    )


@router.post("/clear", response_model=ClearResult)
async def clear(
    user: CurrentUser, db: DBSession, payload: ClearRequest | None = None
) -> ClearResult:
    """Bulk hard-delete — ``scope='read'`` (default) or the explicit ``'all'``.

    POST-as-action rather than DELETE-with-body, consistent with
    ``/read-all``. The body is optional so a bare POST gets the safe
    default scope (Codex review: a required model made the documented
    default unreachable — FastAPI 422s before field defaults apply).
    Idempotent: a repeat call returns ``deleted=0``.
    """
    scope = payload.scope if payload is not None else "read"
    deleted = await notifications_repo.clear_for_user(db, user_id=user.id, scope=scope)
    return ClearResult(deleted=deleted)


@router.post("/read-all", response_model=MarkAllReadResult)
async def mark_all_read(user: CurrentUser, db: DBSession) -> MarkAllReadResult:
    """Mark every unread notification for the current user as read.

    Single round trip instead of N. Returns the count touched so the
    UI can update its badge without another GET.
    """
    touched = await notifications_repo.mark_all_read_for_user(db, user_id=user.id)
    return MarkAllReadResult(marked_read=touched)


@router.post("/{notification_id}/read", response_model=OkResponse)
async def mark_read(notification_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    from app.models.notification import Notification

    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise NotFoundError("Notification not found", code="notification.not_found")
    await notifications_repo.mark_read(db, notification)
    return OkResponse()


@router.post("/{notification_id}/unread", response_model=OkResponse)
async def mark_unread(notification_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    """Two-way read state: clear ``read_at`` so an item can be re-flagged
    for later. Idempotent when already unread."""
    from app.models.notification import Notification

    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise NotFoundError("Notification not found", code="notification.not_found")
    await notifications_repo.mark_unread(db, notification)
    return OkResponse()


@router.delete("/{notification_id}", response_model=OkResponse)
async def delete_one(notification_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    """Hard-delete one notification. 404 for a missing OR foreign id (the
    single-statement ownership gate doesn't leak existence)."""
    deleted = await notifications_repo.delete_for_user(
        db, user_id=user.id, notification_id=notification_id
    )
    if not deleted:
        raise NotFoundError("Notification not found", code="notification.not_found")
    return OkResponse()
