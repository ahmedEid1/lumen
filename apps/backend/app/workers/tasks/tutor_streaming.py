"""Celery task that runs a tutor turn end-to-end (L21a).

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
"""

from __future__ import annotations

import asyncio
import contextlib

import redis.asyncio as redis
from celery.utils.log import get_task_logger

from app.core.config import get_settings
from app.core.cost_scripts import release_concurrency
from app.db.base import get_sessionmaker
from app.models.tutor_turn_job import TURN_STATUS_COMPLETE, TURN_STATUS_FAILED
from app.services.redis_streams import emit_event, set_stream_ttl
from app.services.tutor_orchestrator_stream import orchestrate_stream
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
    Session = get_sessionmaker()

    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
    user_id: str | None = None
    user_message_content = ""
    conversation_id: str | None = None

    try:
        async with Session() as db:
            turn = await claim_pending_turn(db, turn_id)
            if turn is None:
                log.info("tutor_turn_already_claimed", extra={"turn_id": turn_id})
                return
            user_id = turn.user_id
            conversation_id = turn.conversation_id
            await db.commit()

        # Orchestrate + emit events to the Redis stream. The
        # orchestrator yields events; we relay each to Redis.
        async for ev in orchestrate_stream(
            turn_id=turn_id,
            user_id=user_id,
            user_message=user_message_content,
            course_id=None,
        ):
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
        # Release the per-user concurrency slot — plan-v7 §V7-F1 made
        # this user-scoped (was wrongly drafted as turn-scoped in v5).
        if user_id is not None:
            with contextlib.suppress(Exception):
                await release_concurrency(redis_client, user_key=f"concurrent:user:{user_id}")
        with contextlib.suppress(Exception):
            await redis_client.aclose()
        del conversation_id  # currently unused; keeps the linter happy
