from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.email_type import Email
from app.models.user import Role


class UserPublic(BaseModel):
    """Profile fields safe to expose to anyone."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    full_name: str
    avatar_url: str | None = None
    bio: str | None = None
    role: Role


class UserOut(UserPublic):
    """Profile fields for the authenticated user."""

    email: Email
    is_active: bool
    email_verified_at: datetime | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=500)
