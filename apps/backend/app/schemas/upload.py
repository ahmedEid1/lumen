from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=120)
    kind: Literal["avatar", "lesson", "cover", "attachment"]
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)


class PresignResponse(BaseModel):
    # POST presign carries a ``content-length-range`` policy condition
    # that S3 actually enforces server-side; the old PUT presign was
    # advisory only. The client must submit ``fields`` plus a final
    # ``file`` form field via multipart/form-data.
    method: Literal["POST"] = "POST"
    url: str
    fields: dict[str, str]
    key: str
    expires_in: int
    public_url: str
    max_bytes: int
