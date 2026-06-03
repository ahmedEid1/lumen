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
from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentUser, DBSession
from app.core.config import get_settings
from app.core.cost_scripts import (
    USD_TO_MICROCENTS,
    check_concurrency,
    release_concurrency,
    reserve_cost,
)
from app.core.errors import (
    AppError,
    NotFoundError,
    QuotaExceededError,
    TutorConcurrencyLimitError,
    TutorGlobalCapError,
    TutorIpCapError,
    TutorUserCapError,
)
from app.core.ratelimit import limiter
from app.models.llm_call import BILLING_BYOK
from app.models.tutor_turn_job import TERMINAL_TURN_STATUSES, TURN_STATUS_ABORTED
from app.services import byok as byok_service
from app.services.llm_call_log import quota_limits, user_request_count
from app.services.redis_streams import check_trim, consume_stream
from app.services.tutor_turn_service import (
    abort_pending,
    count_active_turns_in_window,
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
    # L32 — optional course context. When set, the Celery worker runs
    # pgvector retrieval against this course's lessons before
    # synthesising. When unset, the orchestrator runs synth-only
    # (degraded mode — fine for /demo).
    course_slug: str | None = None


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
@limiter.limit("20/minute")
async def post_turn(
    body: NewTurnIn,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> TurnOut:
    _require_streaming_enabled()

    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"

    # L32 — resolve course_slug to course_id BEFORE the reservation
    # (Codex L33-rescue P1). If we reserved first and then 404'd on
    # an unknown slug, the reservation would leak until its 24h TTL.
    # Restrict to PUBLISHED courses for the demo path (Codex L32 P1):
    # the streaming surface shouldn't expose draft/archived lessons
    # to logged-in non-owners.
    course_id: str | None = None
    if body.course_slug:
        from sqlalchemy import select

        from app.models.course import Course, CourseStatus

        result = await db.execute(
            select(Course.id).where(
                Course.slug == body.course_slug,
                Course.deleted_at.is_(None),
                Course.status == CourseStatus.published,
            )
        )
        course_id = result.scalar_one_or_none()
        if course_id is None:
            raise NotFoundError("course not found")

    # L33 — cost-cap + concurrency reservation. The order matters:
    # check_concurrency first (cheap, no Lua write happens until ok),
    # then reserve_cost. If the cost reserve fails after the
    # concurrency slot was acquired, we release it before raising.
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    user_concurrency_key = f"concurrent:user:{user.id}"

    async def _release_reservation(*, release_cost: bool = True) -> None:
        """L33-rescue P1: full reservation rollback on post-reserve
        failures. Releases the cost budget (negative-delta reconcile)
        only when this turn actually reserved it — a BYOK turn skips the
        dollar reservation (Gate-A fix), and reconciling unheld cost
        would free platform budget that was never taken. Concurrency is
        always released. Wrapped in suppress because a Redis flake
        during cleanup shouldn't mask the underlying error."""
        import contextlib

        if release_cost:
            with contextlib.suppress(Exception):
                from app.core.cost_scripts import reconcile_cost

                await reconcile_cost(
                    redis_client,
                    user_key=f"cost:user:{user.id}",
                    ip_key=f"cost:ip:{client_ip}",
                    global_key="cost:global",
                    delta_microcents=-settings.tutor_estimate_microcents,
                )
        with contextlib.suppress(Exception):
            await release_concurrency(redis_client, user_key=user_concurrency_key)

    reservation_holds_concurrency = False
    reservation_holds_cost = False
    try:
        conc_ok, _conc_count = await check_concurrency(
            redis_client,
            user_key=user_concurrency_key,
            max_concurrent=settings.tutor_max_concurrent,
        )
        if not conc_ok:
            raise TutorConcurrencyLimitError("Too many concurrent streaming turns for this user.")
        reservation_holds_concurrency = True

        # S5.12/R-S1'': resolve the foreground BYOK context at enqueue time
        # and persist its credential_id on the turn (never the key). The
        # worker re-resolves + decrypts from this id inside its trust
        # boundary. Resolved BEFORE the dollar reservation (Gate-A fix): a
        # BYOK turn pays the user's own provider, so it must neither consume
        # nor be blocked by platform cost buckets (charter decision 5).
        byok_ctx = await byok_service.resolve_context(db, user_id=user.id)

        if byok_ctx.credential_id is not None:
            # Non-dollar BYOK request windows at enqueue (ADR-0027 §5).
            # Terminal streamed turns are visible through the llm_calls
            # rows the worker writes; the in-flight remainder through the
            # non-terminal turn count — together they close the burst
            # undercount. The route limiter + the concurrency slot above
            # stay in force.
            limit_24h, limit_1h = quota_limits(BILLING_BYOK)
            for window_seconds, limit, dimension in (
                (24 * 60 * 60, limit_24h, "requests_24h"),
                (60 * 60, limit_1h, "requests_1h"),
            ):
                used = await user_request_count(db, user.id, window_seconds)
                used += await count_active_turns_in_window(
                    db, user_id=user.id, window_seconds=window_seconds
                )
                if used >= limit:
                    await release_concurrency(redis_client, user_key=user_concurrency_key)
                    reservation_holds_concurrency = False
                    raise QuotaExceededError(
                        "You've reached your request limit for now.",
                        details={"dimension": dimension, "used": used, "limit": limit},
                    )
            # No platform dollar reservation for a BYOK turn; the worker's
            # finally skips reconcile when reserved_microcents == 0.
            reserved_usd = Decimal(0)
        else:
            reserve_ok, reserve_tag = await reserve_cost(
                redis_client,
                user_key=f"cost:user:{user.id}",
                ip_key=f"cost:ip:{client_ip}",
                global_key="cost:global",
                estimate_microcents=settings.tutor_estimate_microcents,
                max_user_microcents=settings.tutor_cap_user_microcents,
                max_ip_microcents=settings.tutor_cap_ip_microcents,
                max_global_microcents=settings.tutor_cap_global_microcents,
            )
            if not reserve_ok:
                # Release the slot we just acquired before raising —
                # otherwise a flat-out-broke caller would slowly drain
                # their own concurrency budget by retrying.
                await release_concurrency(redis_client, user_key=user_concurrency_key)
                reservation_holds_concurrency = False
                if reserve_tag == "user_cap":
                    raise TutorUserCapError("Per-user cost cap reached.")
                if reserve_tag == "ip_cap":
                    raise TutorIpCapError("Per-IP cost cap reached.")
                if reserve_tag == "global_cap":
                    raise TutorGlobalCapError("Global cost cap reached for the day.")
                # invalid_estimate — caller misuse, treat as 4xx.
                raise TutorUserCapError(f"reservation rejected: {reserve_tag}")
            reservation_holds_cost = True

            # The reservation's microcent value converted to USD for the
            # row. Decimal arithmetic so we don't accrue float drift
            # across reconcile + sweep paths.
            reserved_usd = Decimal(settings.tutor_estimate_microcents) / Decimal(USD_TO_MICROCENTS)

        turn = await create_turn(
            db,
            user_id=user.id,
            conversation_id=body.conversation_id,
            reserved_cost_usd=reserved_usd,
            reservation_ip_key=client_ip,
            prompt_template_hash=None,
            user_message=body.content,
            course_id=course_id,
            credential_id=byok_ctx.credential_id,
        )
        # Commit so the after_commit listener fires the Celery enqueue.
        # Once committed, the row + sweep beat own the reservation —
        # the Celery task (or the sweep on worker death) will
        # reconcile/release. We mark the flags false so the except
        # branch doesn't double-release.
        await db.commit()
        reservation_holds_concurrency = False
        reservation_holds_cost = False
    except Exception:
        # L33-rescue P1: if any post-reserve step fails (course
        # resolve already passed, but create_turn / flush / commit
        # could still raise), release the reservation we hold. BYOK
        # turns never hold cost, so only the slot comes back.
        if reservation_holds_concurrency or reservation_holds_cost:
            await _release_reservation(release_cost=reservation_holds_cost)
        raise
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            await redis_client.aclose()

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
        # L33-rescue P1: cancelling a pending row leaks its
        # reservation unless we release here. If the Celery task
        # hasn't claimed it yet, `claim_pending_turn(...)` returns
        # None and the task's finally block skips reconcile/release
        # (user_id is None at that point). Capture the row's
        # reservation metadata before zeroing it, then release in
        # Redis directly. Wrapped in suppress so a Redis flake
        # doesn't block the cancellation itself.
        reserved_microcents = int(turn.reserved_cost_usd * USD_TO_MICROCENTS)
        reservation_ip_key = turn.reservation_ip_key
        user_id_for_release = turn.user_id

        # Confirm-round-2 fix (Codex): "was it unclaimed?" must be decided
        # by the atomic pending→aborted UPDATE itself, not a pre-update
        # ORM read — a worker claiming between the read and the terminal
        # transition made BOTH this path and the worker's finally release
        # the slot (double-decrement → concurrency-cap bypass). When
        # abort_pending reports False the row was already claimed (or
        # terminal): the worker owns the slot, we only mark it aborted.
        was_unclaimed = await abort_pending(
            db, turn_id=turn_id, error_code="tutor.cancelled_by_user"
        )
        if not was_unclaimed:
            await mark_terminal(
                db,
                turn_id=turn_id,
                status=TURN_STATUS_ABORTED,
                error_code="tutor.cancelled_by_user",
            )
        await db.commit()

        # Release semantics: cost reconciles only when this turn actually
        # held a reservation (unchanged); the concurrency slot releases
        # when it held cost (original L33 behavior for claimed turns) OR
        # when the turn was still unclaimed — a zero-reserved BYOK cancel
        # previously leaked its slot until the Redis TTL (confirm-round
        # fix). Claimed turns' slots are the worker finally's job.
        held_cost = reserved_microcents > 0 and reservation_ip_key is not None
        if held_cost or was_unclaimed:
            settings = get_settings()
            redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
            try:
                import contextlib

                from app.core.cost_scripts import reconcile_cost

                if held_cost:
                    with contextlib.suppress(Exception):
                        await reconcile_cost(
                            redis_client,
                            user_key=f"cost:user:{user_id_for_release}",
                            ip_key=f"cost:ip:{reservation_ip_key}",
                            global_key="cost:global",
                            delta_microcents=-reserved_microcents,
                        )
                with contextlib.suppress(Exception):
                    await release_concurrency(
                        redis_client,
                        user_key=f"concurrent:user:{user_id_for_release}",
                    )
            finally:
                import contextlib

                with contextlib.suppress(Exception):
                    await redis_client.aclose()


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
