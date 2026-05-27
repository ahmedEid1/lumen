"""Runtime feature flags — read-only.

A single GET endpoint that returns the current values of the runtime
flags Settings exposes. The frontend polls this on app boot (and on a
60s stale window via TanStack Query) so a flag flip on the server side
becomes visible without any client redeploy.

L20.5 ships the wire shape only — the response reads straight from
:mod:`app.core.config`. L21-Sec adds a Redis-backed override layer
(``runtime_flags:override:<key> -> 0/1``) so an admin can flip a flag
without restarting the API. The endpoint stays anon-readable: nothing
returned here is sensitive, and gating it on auth would force every
public page to know the user's session before it could decide which
code path to mount.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings

router = APIRouter()


class RuntimeFlags(BaseModel):
    """Public runtime-flags payload.

    Every flag here defaults to the value in :class:`Settings`. Adding a
    new flag is two lines (Settings + this schema). Removing or renaming
    one is a breaking change for any client cached behind a CDN — bump a
    version field if that ever becomes a problem; today there's nothing
    to migrate.
    """

    model_config = ConfigDict(from_attributes=False)

    # L21a/L21b — SSE streaming tutor turns. OFF until L21b's flag-flip.
    tutor_streaming: bool


@router.get(
    "/runtime-flags",
    response_model=RuntimeFlags,
    summary="Public runtime feature flags",
    tags=["runtime-flags"],
)
async def get_runtime_flags() -> RuntimeFlags:
    s = get_settings()
    return RuntimeFlags(
        tutor_streaming=s.feature_tutor_streaming,
    )
