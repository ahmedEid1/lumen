from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationKind


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: NotificationKind
    title: str
    body: str
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None
