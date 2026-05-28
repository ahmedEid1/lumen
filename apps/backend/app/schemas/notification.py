from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
