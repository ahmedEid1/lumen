from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserPublic


class DiscussionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    body: str = Field(default="", max_length=10_000)


class DiscussionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=240)
    body: str | None = Field(default=None, max_length=10_000)


class DiscussionReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class DiscussionReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    body: str
    created_at: datetime
    updated_at: datetime
    author: UserPublic | None = None


class DiscussionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    reply_count: int = 0
    last_activity_at: datetime
    author: UserPublic | None = None


class DiscussionDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
    author: UserPublic | None = None
    replies: list[DiscussionReplyOut] = Field(default_factory=list)
    # Iter 90: is the calling viewer subscribed to this thread?
    # Anonymous viewers always see False. Used by the UI to render
    # Subscribe vs Unsubscribe without a second round-trip.
    is_subscribed: bool = False
