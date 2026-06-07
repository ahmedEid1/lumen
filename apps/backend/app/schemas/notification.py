from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # ``kind`` is a plain ``str``, not the ``NotificationKind`` enum, on
    # purpose. The DB column is a ``String(40)`` and the H6 security-alarm
    # path (``services.auth`` → ``notify_admins``) intentionally writes
    # *sub-kinds* that aren't enum members — e.g. ``security.refresh_reuse``
    # — so a new security signal can ship without an enum migration. Typing
    # this as the enum made ``model_validate`` raise on those rows, which
    # 500'd ``GET /me/notifications`` for any admin who'd received a
    # refresh-reuse alarm while every student's bell kept working. The bell
    # UI already treats ``kind`` as an open string (switch with a default),
    # so widening here keeps the contract honest without losing anything.
    kind: str
    title: str
    body: str
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None


class MarkAllReadResult(BaseModel):
    """Typed replacement for the old ``response_model=dict`` on read-all.

    Wire payload is unchanged (``{ok, marked_read}``) — this only gives the
    OpenAPI contract (and the generated TS client) a real named shape.
    """

    ok: bool = True
    marked_read: int


class ClearRequest(BaseModel):
    """Bulk-clear scope. ``read`` (default) deletes only rows already read;
    ``all`` is the explicit opt-in that also destroys unread rows."""

    scope: Literal["read", "all"] = "read"


class ClearResult(BaseModel):
    ok: bool = True
    deleted: int


class UnreadCountOut(BaseModel):
    """Cheap badge payload — one COUNT, no row hydration.

    The bell polls this every 60s instead of pulling 50 full rows; it is
    also the only badge source that stays accurate past the newest-50 cap
    of the bare list endpoint.
    """

    unread_count: int = Field(ge=0)
