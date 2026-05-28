"""Sweep + orphan-cleanup beat tasks (L21a).

Two periodic jobs:

- :func:`sweep_dead_turns` — runs every 10 s (pending) + 30 s
  (running/streaming). Marks rows whose ``updated_at`` is >60 s old
  as ``failed``, releases their reserved cost via ``RECONCILE_COST``.
  Idempotent on Redis failure (plan-v7 §V7-F3) — phase ordering:
  Redis release FIRST, then DB transition. If Redis fails, row stays
  unreleased; next sweep retries.

- :func:`cleanup_orphan_streams` — runs every 5 min. Scans for
  ``tutor:turn:*`` keys whose corresponding DB row is terminal or
  missing, and DELs them. Defense against streams created but never
  TTL'd by a crashing worker.
"""

from __future__ import annotations

import asyncio
import contextlib

import redis.asyncio as redis
from celery.utils.log import get_task_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.cost_scripts import reconcile_cost
from app.db.base import make_worker_engine
from app.workers.celery_app import celery

log = get_task_logger(__name__)


@celery.task(name="tutor.sweep_dead_turns.v1", bind=True, max_retries=0)
def sweep_dead_turns(self) -> None:
    """Mark stale pending/running/streaming rows as failed.

    Two-phase per plan-v7 §V7-F3:
      1. Redis: release the reservation. If this raises, leave the
         row alone so the next sweep retries.
      2. DB: flip the status to failed.

    Also picks up already-`failed` rows whose ``reserved_cost_usd > 0``
    so a previous-sweep Redis-failure gets retried next tick.
    """
    asyncio.run(_sweep_async())


async def _sweep_async() -> None:
    settings = get_settings()
    # Per-task NullPool engine (fresh asyncio.run loop per Celery task);
    # disposed in the finally. See app.db.base.make_worker_engine.
    engine = make_worker_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)

    try:
        async with Session() as db:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, user_id, reservation_ip_key,
                               reserved_cost_usd, status
                        FROM tutor_turn_jobs
                        WHERE (
                            status IN ('pending', 'running', 'streaming')
                            AND updated_at < NOW() - interval '60 seconds'
                        ) OR (
                            status IN ('failed', 'aborted')
                            AND reserved_cost_usd > 0
                        )
                        ORDER BY updated_at
                        LIMIT 50
                        FOR UPDATE SKIP LOCKED
                        """
                    )
                )
            ).fetchall()

            for row in rows:
                try:
                    user_key = f"cost:user:{row.user_id}"
                    ip_key = (
                        f"cost:ip:{row.reservation_ip_key}"
                        if row.reservation_ip_key
                        else f"cost:ip:unknown:{row.id}"
                    )
                    global_key = "cost:global"
                    microcents = -int(float(row.reserved_cost_usd) * 1_000_000)
                    if microcents != 0:
                        await reconcile_cost(
                            redis_client,
                            user_key=user_key,
                            ip_key=ip_key,
                            global_key=global_key,
                            delta_microcents=microcents,
                        )
                except Exception as exc:
                    log.warning(
                        "tutor_sweep_redis_release_failed",
                        extra={"turn_id": row.id, "err": str(exc)},
                    )
                    # Don't update the row; next sweep retries.
                    continue

                # Phase 2: DB transition + zero the reservation so a
                # re-sweep doesn't double-release.
                await db.execute(
                    text(
                        """
                        UPDATE tutor_turn_jobs
                        SET status = CASE
                                WHEN status IN ('pending', 'running', 'streaming')
                                THEN 'failed'
                                ELSE status
                            END,
                            error_code = COALESCE(error_code, 'tutor.worker_died'),
                            reserved_cost_usd = 0,
                            updated_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {"id": row.id},
                )

            await db.commit()
    finally:
        with contextlib.suppress(Exception):
            await redis_client.aclose()
        with contextlib.suppress(Exception):
            await engine.dispose()


@celery.task(name="tutor.cleanup_orphan_streams.v1", bind=True, max_retries=0)
def cleanup_orphan_streams(self) -> None:
    """Drop tutor:turn:* Redis keys whose DB row is terminal/missing.

    Cheap, infrequent (5 min). Guards against leaks when a worker
    crashes between emitting events and setting a TTL.
    """
    asyncio.run(_cleanup_async())


async def _cleanup_async() -> None:
    settings = get_settings()
    # Per-task NullPool engine (fresh asyncio.run loop per Celery task);
    # disposed in the finally. See app.db.base.make_worker_engine.
    engine = make_worker_engine()
    Session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=False)

    try:
        # SCAN tutor:turn:* and check each against the DB. Iteration
        # is bounded by count=200 per batch so we don't OOM on a
        # large-scale leak.
        cursor = 0
        async with Session() as db:
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor, match=b"tutor:turn:*", count=200
                )
                for raw_key in keys:
                    key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
                    turn_id = key.split(":", 2)[-1]
                    row = await db.execute(
                        text("SELECT status FROM tutor_turn_jobs WHERE id = :id"),
                        {"id": turn_id},
                    )
                    status = row.scalar()
                    if status is None or status in (
                        "complete",
                        "failed",
                        "aborted",
                    ):
                        await redis_client.delete(raw_key)
                if cursor == 0:
                    break
    finally:
        with contextlib.suppress(Exception):
            await redis_client.aclose()
        with contextlib.suppress(Exception):
            await engine.dispose()
