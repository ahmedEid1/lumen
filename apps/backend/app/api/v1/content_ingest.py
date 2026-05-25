"""Phase E3 — content-ingest HTTP endpoints.

Two routes:

* ``POST /studio/ingest/preview`` — body ``{url}``. Returns a typed
  :class:`IngestPayload` for the instructor to review. No persistence.
* ``POST /studio/ingest/commit`` — body ``{course_id, payload}``.
  Creates the modules + lessons on the named course.

Both routes require instructor / admin and are rate-limited at
3/min/user (extraction is expensive and can hit upstream limits).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DBSession, RequireInstructor
from app.core.ratelimit import limiter
from app.services.content_ingest import (
    IngestPayload,
    SourceKind,
    commit_payload,
    detect_source,
    ingest,
)

router = APIRouter()


# ---------- Wire schemas ----------


class IngestPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=500)


class IngestDetectResponse(BaseModel):
    source: SourceKind


class IngestCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str = Field(min_length=1, max_length=64)
    payload: IngestPayload


class IngestCommitResponse(BaseModel):
    course_id: str
    modules: int
    lessons: int


# ---------- Endpoints ----------


@router.post("/detect", response_model=IngestDetectResponse)
@limiter.limit("60/minute")
async def detect_ingest_source(
    payload: IngestPreviewRequest,
    _: RequireInstructor,
    request: Request,  # noqa: ARG001 — slowapi binds the bucket key off this
    response: Response,  # noqa: ARG001 — slowapi injects rate-limit headers
) -> IngestDetectResponse:
    """Cheap regex-only source detection — separated from the heavy
    ``/preview`` call so the studio modal can render "Detected:
    YouTube" before the user opts into a real extraction. Higher rate
    limit because no I/O happens."""
    return IngestDetectResponse(source=detect_source(payload.url))


@router.post("/preview", response_model=IngestPayload, status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def preview_ingest(
    payload: IngestPreviewRequest,
    _: RequireInstructor,
    request: Request,  # noqa: ARG001 — slowapi binds the bucket key off this
    response: Response,  # noqa: ARG001 — slowapi injects rate-limit headers
) -> IngestPayload:
    """Fetch + parse the URL, return a draft payload. No persistence.

    The extractor may take a few seconds (a long YouTube video can
    have a ~50KB transcript). For v1 we block the request rather than
    spinning up a background task; the rate limit (3/min/user) plus
    the upstream call timeout keep this from blowing up the API.
    """
    return ingest(payload.url)


@router.post(
    "/commit",
    response_model=IngestCommitResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def commit_ingest(
    payload: IngestCommitRequest,
    user: RequireInstructor,
    db: DBSession,
    request: Request,  # noqa: ARG001 — slowapi binds the bucket key off this
    response: Response,  # noqa: ARG001 — slowapi injects rate-limit headers
) -> IngestCommitResponse:
    """Materialise a previously-previewed payload into the named
    course. The caller is expected to have just reviewed and
    (optionally) edited the payload in the studio modal — the server
    treats the payload as authoritative and appends rather than
    overwriting any existing modules."""
    counts = await commit_payload(
        db,
        course_id=payload.course_id,
        owner=user,
        payload=payload.payload,
    )
    return IngestCommitResponse(
        course_id=payload.course_id,
        modules=counts["modules"],
        lessons=counts["lessons"],
    )
