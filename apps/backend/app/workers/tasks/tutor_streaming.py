"""Celery task that runs a tutor turn end-to-end (L21a → L32).

Per ADR-0017/0019:

- ``bind=True`` + ``max_retries=0`` + ``acks_late=True``. We don't
  want auto-retry on a soft failure because each retry burns LLM
  cost; the sweep beat marks the row failed and the client's poll
  loop sees a clean error.
- Atomic phase fence via ``claim_pending_turn`` — only one worker
  proceeds.
- ``asyncio.run()`` inside the sync task wraps the async
  orchestrator (ADR-0017).
- ``finally`` block wraps every cleanup in ``contextlib.suppress``
  so a Redis flake doesn't skip the next cleanup step (plan-v7
  §V7-F7).

L32 — pgvector retrieval runs HERE (not inside orchestrate_stream)
so the orchestrator stays a pure async generator with no DB session.
After the phase-fence we resolve the course row + run the retriever
sub-agent + then pass the chunks to ``orchestrate_stream``.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from decimal import Decimal

import redis.asyncio as redis
from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.cost_scripts import (
    USD_TO_MICROCENTS,
    reconcile_cost,
    release_concurrency,
    reserve_cost,
)
from app.db.base import make_worker_engine
from app.models.course import Course
from app.models.llm_call import BILLING_BYOK, BILLING_PLATFORM, STATUS_ERROR, STATUS_OK
from app.models.tutor_turn_job import TURN_STATUS_COMPLETE, TURN_STATUS_FAILED
from app.services import account as account_service
from app.services import byok as byok_service
from app.services.llm_call_log import record_streamed_turn_row
from app.services.redis_streams import emit_event, set_stream_ttl
from app.services.tutor_orchestrator_stream import orchestrate_stream
from app.services.tutor_subagents.retriever import RetrieverChunk
from app.services.tutor_subagents.retriever import run as run_retriever
from app.services.tutor_turn_service import claim_pending_turn, mark_terminal, set_reserved_cost
from app.workers.celery_app import celery

log = get_task_logger(__name__)


@celery.task(
    name="tutor.run_turn.v1",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def run_turn(self, turn_id: str) -> None:
    """Run a tutor turn. Wraps the async orchestrator in ``asyncio.run``.

    The task itself is sync (Celery's prefork pool's expectation —
    ADR-0017). The async work happens inside the body.
    """
    asyncio.run(_run_turn_async(turn_id))


class PlatformFallbackCapError(RuntimeError):
    """A BYOK turn fell back to platform in the worker but the platform
    cost reservation refused (confirm-round fix). Fails the turn via the
    generic handler — error_code ``tutor.runtime: PlatformFallbackCapError``."""


def _stream_provider_name(byok_dispatch: dict[str, str] | None) -> str:
    """Provider label for the streamed turn's llm_calls row."""
    if byok_dispatch:
        return byok_dispatch.get("transport", "byok")
    return str(getattr(get_settings(), "llm_provider", "platform") or "platform")


def _stream_model_name(byok_dispatch: dict[str, str] | None) -> str:
    """Model label for the streamed turn's llm_calls row."""
    if byok_dispatch:
        return byok_dispatch.get("model", "unknown")
    return str(getattr(get_settings(), "llm_model", "") or "unknown")


async def _run_turn_async(turn_id: str) -> None:
    settings = get_settings()
    # Per-task NullPool engine — a Celery prefork task gets a fresh
    # event loop, so the module-level pooled engine can't be reused
    # here without "got Future attached to a different loop". Disposed
    # in the finally below. See app.db.base.make_worker_engine.
    engine = make_worker_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    user_id: str | None = None
    user_message_content = ""
    course_id: str | None = None
    conversation_id: str | None = None
    retrieved_chunks: list[RetrieverChunk] = []
    retrieval_latency_ms: int | None = None
    # L33 — reservation metadata captured at claim time so we can
    # reconcile the bucket whether the turn completes, fails, or is
    # cancelled mid-stream.
    reserved_microcents: int = 0
    reservation_ip_key: str | None = None
    actual_cost_microcents: int = 0
    credential_id: str | None = None
    byok_dispatch: dict[str, str] | None = None
    final_cost_usd: float = 0.0
    final_total_ms: int = 0
    # S7 — provider-reported token usage carried off the terminal
    # turn_complete event. Stays 0 if the stream dies before the usage chunk
    # arrives (failure/abort) so the persisted row claims only what the
    # provider actually billed. Observability/cost only — streaming quota
    # stays COUNT-based (see record_streamed_turn_row's QUOTA INVARIANT note).
    final_prompt_tokens: int = 0
    final_completion_tokens: int = 0

    try:
        async with Session() as db:
            turn = await claim_pending_turn(db, turn_id)
            if turn is None:
                log.info("tutor_turn_already_claimed", extra={"turn_id": turn_id})
                return
            user_id = turn.user_id
            conversation_id = turn.conversation_id
            course_id = turn.course_id
            user_message_content = turn.user_message or ""
            reservation_ip_key = turn.reservation_ip_key
            credential_id = turn.credential_id
            # The row stores USD as Decimal; convert back to the
            # integer microcent shape the reconcile Lua expects.
            reserved_microcents = int(turn.reserved_cost_usd * USD_TO_MICROCENTS)
            await db.commit()

        # S5.12/R-S1'': re-resolve + decrypt the user's BYOK key IN THE WORKER
        # from the carried credential_id (never the key bytes — FR-BYOK-26).
        # Returns None for the platform path (no cred / flag off / consented
        # drift-fallback). NOT wrapped in suppress (Gate-A fix): a
        # no-consent drift raises ByokModelUnavailableError, which must FAIL
        # the turn via the generic handler below — swallowing it silently
        # dispatched the turn on the platform model against the user's
        # explicit allow_platform_fallback=False.
        if credential_id:
            async with Session() as db:
                byok_dispatch = await byok_service.stream_dispatch_for_turn(
                    db, credential_id=credential_id, user_id=user_id
                )
                # _handle_drift may have flushed needs_attention — persist it.
                await db.commit()

            if byok_dispatch is None:
                # Confirm-round fix: the enqueue path skipped the platform
                # dollar reservation because this turn resolved BYOK — but
                # the credential fell back to platform here (consented
                # drift / disabled / flag flipped between enqueue and run).
                # The dispatch below WILL spend platform dollars, so
                # reserve them now, worker-side; a refusal fails the turn
                # exactly like the API-side cap errors. The row's
                # reserved_cost_usd is updated so the cancel path and the
                # sweep see the truth, and reserved_microcents feeds the
                # finally-reconcile as usual.
                settings_now = get_settings()
                reserve_ok, reserve_tag = await reserve_cost(
                    redis_client,
                    user_key=f"cost:user:{user_id}",
                    ip_key=f"cost:ip:{reservation_ip_key or 'unknown'}",
                    global_key="cost:global",
                    estimate_microcents=settings_now.tutor_estimate_microcents,
                    max_user_microcents=settings_now.tutor_cap_user_microcents,
                    max_ip_microcents=settings_now.tutor_cap_ip_microcents,
                    max_global_microcents=settings_now.tutor_cap_global_microcents,
                )
                if not reserve_ok:
                    raise PlatformFallbackCapError(
                        f"platform fallback rejected by cost reservation: {reserve_tag}"
                    )
                reserved_microcents = int(settings_now.tutor_estimate_microcents)
                async with Session() as db:
                    await set_reserved_cost(
                        db,
                        turn_id=turn_id,
                        reserved_cost_usd=Decimal(reserved_microcents) / Decimal(USD_TO_MICROCENTS),
                    )
                    await db.commit()

        # L32 — pgvector retrieval. Best-effort: a retrieval failure
        # degrades to "no course context" but doesn't fail the turn.
        # The orchestrator decides whether to ground synth on the
        # chunks based on whether we hand any in.
        if course_id and user_message_content.strip():
            with contextlib.suppress(Exception):
                async with Session() as db:
                    course = (
                        await db.execute(select(Course).where(Course.id == course_id))
                    ).scalar_one_or_none()
                    if course is not None:
                        t0 = time.monotonic()
                        # Course-scoped retrieval. ``audit=True`` (the
                        # default) inside the sub-agent writes a
                        # retrieval_audits row so the admin
                        # observability surface gets a real trace.
                        result = await run_retriever(
                            db,
                            course=course,
                            query=user_message_content,
                            user_id=user_id,
                            top_k=6,
                            feature="tutor.streaming",
                        )
                        retrieval_latency_ms = int((time.monotonic() - t0) * 1000)
                        retrieved_chunks = list(result.chunks)
                        await db.commit()

        # Orchestrate + emit events to the Redis stream. The
        # orchestrator yields events; we relay each to Redis.
        # L33 — intercept turn_complete to capture the real cost
        # so the finally block can reconcile the reservation.
        # R-S10 cooperative cancellation (ADR-0030 §D4): one heartbeat session
        # for the whole stream — each event tick re-reads is_active through it
        # (assert_account_active issues a fresh SELECT so it sees a flip
        # committed by another transaction). One session, not one-per-event.
        async with Session() as hb_db:
            async for ev in orchestrate_stream(
                turn_id=turn_id,
                user_id=user_id,
                user_message=user_message_content,
                course_id=course_id,
                retrieved_chunks=retrieved_chunks or None,
                retrieval_latency_ms=retrieval_latency_ms,
                byok_dispatch=byok_dispatch,
            ):
                # If the user was suspended/deleted mid-stream, assert_account_
                # active raises account.access_revoked and we stop emitting /
                # close the stream rather than running the turn to completion.
                if user_id:
                    await account_service.assert_account_active(hb_db, user_id)
                if ev["event"] == "turn_complete":
                    cost_usd = float(ev["data"].get("cost_usd", 0.0) or 0.0)
                    actual_cost_microcents = int(cost_usd * USD_TO_MICROCENTS)
                    final_cost_usd = cost_usd
                    final_total_ms = int(float(ev["data"].get("total_ms", 0) or 0))
                    # S7 — provider usage off the terminal chunk for the
                    # llm_calls row (observability/cost only; quota stays
                    # COUNT-based).
                    final_prompt_tokens = int(ev["data"].get("prompt_tokens", 0) or 0)
                    final_completion_tokens = int(ev["data"].get("completion_tokens", 0) or 0)
                await emit_event(
                    redis_client,
                    turn_id=turn_id,
                    event=ev["event"],
                    data=ev["data"],
                )

        # Terminal DB transition + stream TTL. The llm_calls row makes the
        # streamed turn visible to the non-dollar request windows and the
        # admin billing_mode rollup (Gate-B fix / ADR-0027 §Consequences —
        # streamed turns previously wrote no row at all).
        async with Session() as db:
            await mark_terminal(db, turn_id=turn_id, status=TURN_STATUS_COMPLETE)
            await record_streamed_turn_row(
                db,
                user_id=user_id,
                provider=_stream_provider_name(byok_dispatch),
                model=_stream_model_name(byok_dispatch),
                cost_usd=final_cost_usd,
                latency_ms=final_total_ms,
                status=STATUS_OK,
                error_kind=None,
                billing_mode=BILLING_BYOK if byok_dispatch else BILLING_PLATFORM,
                prompt_tokens=final_prompt_tokens,
                completion_tokens=final_completion_tokens,
            )
            await db.commit()

        with contextlib.suppress(Exception):
            await set_stream_ttl(redis_client, turn_id=turn_id)

    except Exception as exc:
        log.exception("tutor_turn_failed", extra={"turn_id": turn_id})
        # ADR-0027 §4 item 3, streaming arm (Gate-B fix): an auth-class
        # provider failure on a BYOK stream marks the credential invalid;
        # the user's next turn resolves to platform (items 1/5) and the
        # credential banner carries the notice. Best-effort by design.
        if credential_id is not None and byok_service.is_auth_error(exc):
            with contextlib.suppress(Exception):
                async with Session() as db:
                    await byok_service.mark_credential_invalid(db, credential_id)
                    await db.commit()
        # Best-effort: mark the row failed + emit a turn_failed event.
        # Both wrapped in suppress so a DB-down or Redis-down state
        # doesn't trip another exception during cleanup.
        with contextlib.suppress(Exception):
            async with Session() as db:
                await mark_terminal(
                    db,
                    turn_id=turn_id,
                    status=TURN_STATUS_FAILED,
                    error_code=f"tutor.runtime: {type(exc).__name__}",
                )
                if user_id is not None:
                    # Failed turns count toward the request windows too —
                    # a failing key must not grant unmetered retries.
                    await record_streamed_turn_row(
                        db,
                        user_id=user_id,
                        provider=_stream_provider_name(byok_dispatch),
                        model=_stream_model_name(byok_dispatch),
                        cost_usd=0.0,
                        latency_ms=0,
                        status=STATUS_ERROR,
                        error_kind=type(exc).__name__,
                        billing_mode=BILLING_BYOK if byok_dispatch else BILLING_PLATFORM,
                    )
                await db.commit()
        with contextlib.suppress(Exception):
            await emit_event(
                redis_client,
                turn_id=turn_id,
                event="turn_failed",
                data={"error_code": f"tutor.runtime: {type(exc).__name__}"},
            )
        with contextlib.suppress(Exception):
            await set_stream_ttl(redis_client, turn_id=turn_id)
        raise

    finally:
        # L33 — reconcile the reservation. delta = actual - reserved.
        # On failure/abort, actual is 0 (no LLM tokens spent) so we
        # release the full reservation. On success the delta closes
        # the gap between the conservative estimate and reality.
        # Wrapped in suppress so a Redis flake during reconcile
        # doesn't trip another exception before the slot release.
        if user_id is not None and reserved_microcents > 0 and reservation_ip_key is not None:
            delta = actual_cost_microcents - reserved_microcents
            with contextlib.suppress(Exception):
                await reconcile_cost(
                    redis_client,
                    user_key=f"cost:user:{user_id}",
                    ip_key=f"cost:ip:{reservation_ip_key}",
                    global_key="cost:global",
                    delta_microcents=delta,
                )

        # Release the per-user concurrency slot — plan-v7 §V7-F1 made
        # this user-scoped (was wrongly drafted as turn-scoped in v5).
        if user_id is not None:
            with contextlib.suppress(Exception):
                await release_concurrency(redis_client, user_key=f"concurrent:user:{user_id}")
        with contextlib.suppress(Exception):
            await redis_client.aclose()
        with contextlib.suppress(Exception):
            await engine.dispose()
        del conversation_id  # currently unused; keeps the linter happy
