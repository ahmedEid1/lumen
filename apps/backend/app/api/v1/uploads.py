"""Upload signing endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.upload import PresignRequest, PresignResponse
from app.services import uploads as uploads_service

router = APIRouter()


@router.post("/sign", response_model=PresignResponse)
async def sign_upload(payload: PresignRequest, user: CurrentUser) -> PresignResponse:
    info = uploads_service.sign_upload(
        user=user,
        filename=payload.filename,
        content_type=payload.content_type,
        kind=payload.kind,
        size_bytes=payload.size_bytes,
    )
    return PresignResponse(
        url=str(info["url"]),
        fields=info["fields"],  # type: ignore[arg-type]
        key=str(info["key"]),
        expires_in=int(info["expires_in"]),  # type: ignore[arg-type]
        public_url=str(info["public_url"]),
        max_bytes=int(info["max_bytes"]),  # type: ignore[arg-type]
    )
