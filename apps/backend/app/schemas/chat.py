from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserPublic


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    body: str
    created_at: datetime
    author: UserPublic


class ChatHistoryPage(BaseModel):
    items: list[ChatMessageOut]
    next_cursor: str | None = None


class ChatSendRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
