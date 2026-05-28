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

import redis.asyncio as redis
from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.cost_scripts import (
    USD_TO_MICROCENTS,
    reconcile_cost,
    release_concurrency,
)
from app.db.base import make_worker_engine
from app.models.course import Course
from app.models.tutor_turn_job import TURN_STATUS_COMPLETE, TURN_STATUS_FAILED
from app.services.redis_streams import emit_event, set_stream_ttl
from app.services.tutor_orchestrator_stream import orchestrate_stream
from app.services.tutor_subagents.retriever import RetrieverChunk
from app.services.tutor_subagents.retriever import run as run_retriever
from app.services.tutor_turn_service import claim_pending_turn, mark_terminal
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
            # The row stores USD as Decimal; convert back to the
            # integer microcent shape the reconcile Lua expects.
            reserved_microcents = int(turn.reserved_cost_usd * USD_TO_MICROCENTS)
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
        async for ev in orchestrate_stream(
            turn_id=turn_id,
            user_id=user_id,
            user_message=user_message_content,
            course_id=course_id,
            retrieved_chunks=retrieved_chunks or None,
            retrieval_latency_ms=retrieval_latency_ms,
        ):
            if ev["event"] == "turn_complete":
                cost_usd = float(ev["data"].get("cost_usd", 0.0) or 0.0)
                actual_cost_microcents = int(cost_usd * USD_TO_MICROCENTS)
            await emit_event(
                redis_client,
                turn_id=turn_id,
                event=ev["event"],
                data=ev["data"],
            )

        # Terminal DB transition + stream TTL.
        async with Session() as db:
            await mark_terminal(db, turn_id=turn_id, status=TURN_STATUS_COMPLETE)
            await db.commit()

        with contextlib.suppress(Exception):
            await set_stream_ttl(redis_client, turn_id=turn_id)

    except Exception as exc:
        log.exception("tutor_turn_failed", extra={"turn_id": turn_id})
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
