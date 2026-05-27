"""Streaming tutor endpoints (L21a).

Four endpoints + one shared schema:

- ``POST   /api/v1/tutor/turns``        — open a new streaming turn.
- ``GET    /api/v1/tutor/turns/{tid}/status`` — poll terminal state.
- ``GET    /api/v1/tutor/turns/{tid}/stream`` — SSE event source.
- ``DELETE /api/v1/tutor/turns/{tid}``   — cancel.

ALL four are gated on ``settings.feature_tutor_streaming``. While the
flag is OFF (the L21a-shipped default), every endpoint returns 503
``tutor.streaming_disabled``. L21b's flag-flip turns them on; until
then the existing /tutor/conversations/* path stays canonical.

The SSE event wire shape matches what
``services/tutor_orchestrator_stream.py::orchestrate_stream`` yields —
see that module for the event catalogue.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import redis.asyncio as redis
from fastapi import APIRouter, Header, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentUser, DBSession
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.models.tutor_turn_job import TERMINAL_TURN_STATUSES, TURN_STATUS_ABORTED
from app.services.redis_streams import check_trim, consume_stream
from app.services.tutor_turn_service import (
    create_turn,
    get_turn_for_user,
    mark_terminal,
)

router = APIRouter()


# ---------- Errors ----------


class StreamingDisabledError(AppError):
    """503 — feature_tutor_streaming is OFF.

    The existing non-streaming POST path remains available; this
    error nudges the client to fall back rather than retry.
    """

    status_code = 503
    code = "tutor.streaming_disabled"


_DISABLED_MESSAGE = (
    "Tutor streaming is not enabled on this deployment. "
    "Use POST /api/v1/tutor/conversations/{id}/messages instead."
)


def _require_streaming_enabled() -> None:
    if not get_settings().feature_tutor_streaming:
        raise StreamingDisabledError(_DISABLED_MESSAGE)


# ---------- Schemas ----------


class NewTurnIn(BaseModel):
    """Body for POST /tutor/turns."""

    content: str
    conversation_id: str | None = None


class TurnOut(BaseModel):
    """Response for POST and GET status."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    error_code: str | None = None
    conversation_id: str | None = None


# ---------- POST /tutor/turns ----------


@router.post(
    "/tutor/turns",
    response_model=TurnOut,
    status_code=status.HTTP_201_CREATED,
    summary="Open a streaming tutor turn (L21a)",
    tags=["tutor-streaming"],
)
async def post_turn(
    body: NewTurnIn,
    user: CurrentUser,
    db: DBSession,
    request: Request,
) -> TurnOut:
    _require_streaming_enabled()

    # L21-Sec primitives are wired in but the cost-cap RESERVE is
    # deferred to a follow-up — we want the wire shape live first,
    # then layer the reservation in once the orchestrator is doing
    # real LLM work. For now the row's reserved_cost is 0.
    client_ip = request.client.host if request.client else "unknown"
    turn = await create_turn(
        db,
        user_id=user.id,
        conversation_id=body.conversation_id,
        reserved_cost_usd=Decimal("0"),
        reservation_ip_key=client_ip,
        prompt_template_hash=None,
    )
    # Commit so the after_commit listener fires the Celery enqueue.
    await db.commit()

    return TurnOut(
        id=turn.id,
        status=turn.status,
        error_code=turn.error_code,
        conversation_id=turn.conversation_id,
    )


# ---------- GET /tutor/turns/{tid}/status ----------


@router.get(
    "/tutor/turns/{turn_id}/status",
    response_model=TurnOut,
    summary="Poll a turn's terminal state (L21a)",
    tags=["tutor-streaming"],
)
async def get_turn_status(
    turn_id: str,
    user: CurrentUser,
    db: DBSession,
) -> TurnOut:
    _require_streaming_enabled()

    turn = await get_turn_for_user(db, turn_id=turn_id, user_id=user.id)
    if turn is None:
        # IDOR-safe: 404 even when the row exists but belongs to
        # someone else, so the endpoint isn't an existence oracle.
        raise NotFoundError("turn not found")
    return TurnOut(
        id=turn.id,
        status=turn.status,
        error_code=turn.error_code,
        conversation_id=turn.conversation_id,
    )


# ---------- DELETE /tutor/turns/{tid} ----------


@router.delete(
    "/tutor/turns/{turn_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Abort an in-flight turn (L21a)",
    tags=["tutor-streaming"],
)
async def cancel_turn(turn_id: str, user: CurrentUser, db: DBSession) -> None:
    _require_streaming_enabled()

    turn = await get_turn_for_user(db, turn_id=turn_id, user_id=user.id)
    if turn is None:
        raise NotFoundError("turn not found")
    if turn.status not in TERMINAL_TURN_STATUSES:
        await mark_terminal(
            db,
            turn_id=turn_id,
            status=TURN_STATUS_ABORTED,
            error_code="tutor.cancelled_by_user",
        )
        await db.commit()


# ---------- GET /tutor/turns/{tid}/stream (SSE) ----------


@router.get(
    "/tutor/turns/{turn_id}/stream",
    summary="SSE stream of a tutor turn (L21a)",
    tags=["tutor-streaming"],
    response_class=StreamingResponse,
)
async def stream_turn(
    turn_id: str,
    user: CurrentUser,
    db: DBSession,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    _require_streaming_enabled()

    turn = await get_turn_for_user(db, turn_id=turn_id, user_id=user.id)
    if turn is None:
        raise NotFoundError("turn not found")

    settings = get_settings()
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)

    async def _event_source():
        try:
            # Stale-Last-Event-ID detection (plan-v7 §V7-F4).
            needs_resync, _first_kept = await check_trim(
                redis_client, turn_id=turn_id, last_event_id=last_event_id or ""
            )
            if needs_resync:
                yield {
                    "event": "trim_detected",
                    "data": '{"hint":"resync via /status"}',
                }
                return

            # Codex rescue (L21a-22 arc): initial subscription must
            # start at `0-0` to replay any events the Celery worker
            # emitted BEFORE the browser opened this GET (very likely
            # on the fast noop path — and on real LLM paths the
            # planner_start event happens within ms). `$` would only
            # return new-after-XREAD, so the UI would sit blank.
            # `Last-Event-ID` (resume) takes precedence when present.
            offset = last_event_id or "0-0"
            try:
                async for entry_id, event_name, _data_dict in consume_stream(
                    redis_client, turn_id=turn_id, last_event_id=offset
                ):
                    # Codex rescue: the SSE `data` field must be JSON
                    # — the frontend reducer calls `JSON.parse(ev.data)`.
                    # Earlier shape was `_data_dict.__str__()` (Python
                    # repr with single quotes / `None`), which loses
                    # `synth_chunk.delta` in the parse-error branch.
                    yield {
                        "id": entry_id,
                        "event": event_name,
                        "data": json.dumps(_data_dict or {}),
                    }
                    if event_name in (
                        "turn_complete",
                        "turn_failed",
                        "turn_aborted",
                    ):
                        return
            except asyncio.CancelledError:
                # Client closed the connection. Don't try to recover.
                raise
        finally:
            import contextlib

            with contextlib.suppress(Exception):
                await redis_client.aclose()

    return EventSourceResponse(_event_source())
