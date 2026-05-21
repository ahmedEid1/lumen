from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=120)
    kind: Literal["avatar", "lesson", "cover", "attachment"]
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)


class PresignResponse(BaseModel):
    method: Literal["PUT"] = "PUT"
    url: str
    key: str
    headers: dict[str, str] = {}
    expires_in: int
    public_url: str
