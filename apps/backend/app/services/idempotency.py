"""Idempotency-key lookup/record helper (ADR-0028 §Decision.2, S4.6).

Clone is the first endpoint to honor ``Idempotency-Key`` (ADR-0028 §Consequences),
seeding this infrastructure for the rest of v1. The contract is intentionally
narrow:

* :func:`lookup` — given ``(user_id, key, endpoint)`` return the prior durable
  result id (the committed clone's course id) if a non-expired row exists, else
  ``None``. A replay returns the same course id; the asset task is NOT re-enqueued
  (the tree is the durable unit — ADR-0028 §"Open risks").
* :func:`record` — write the ``(user_id, key)`` row pointing at the committed
  result, with a 24h replay window. Idempotent on ``uq_idem_user_key``: a
  concurrent double-submit that lost the unique-constraint race resolves to the
  winner's result via :func:`lookup`.

The 24h TTL bounds replay; a periodic sweep (out of scope here) reclaims expired
rows. All writes ride the caller's transaction so a rolled-back clone leaves no
idempotency row (the key is free to retry).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency import IdempotencyKey

#: Replay window for clone (ADR-0028 §Decision.2 — 24h TTL).
CLONE_IDEMPOTENCY_TTL = timedelta(hours=24)


async def lookup(db: AsyncSession, *, user_id: str, key: str, endpoint: str) -> str | None:
    """Return the prior ``response_target_id`` for a live key, else ``None``.

    A row whose ``expires_at`` is in the past is treated as absent (the key is
    free to be reused for a fresh mutation) — the sweep eventually drops it.
    """
    now = datetime.now(UTC)
    res = await db.execute(
        select(IdempotencyKey.response_target_id).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.idempotency_key == key,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.expires_at > now,
        )
    )
    return res.scalar_one_or_none()


async def record(
    db: AsyncSession,
    *,
    user_id: str,
    key: str,
    endpoint: str,
    response_target_id: str,
    ttl: timedelta = CLONE_IDEMPOTENCY_TTL,
) -> IdempotencyKey:
    """Persist the ``(user_id, key)`` → result mapping for the replay window.

    Flushed inside the caller's transaction so it commits atomically with the
    durable result; a rolled-back clone never leaves a key behind.
    """
    row = IdempotencyKey(
        user_id=user_id,
        idempotency_key=key,
        endpoint=endpoint,
        response_target_id=response_target_id,
        expires_at=datetime.now(UTC) + ttl,
    )
    db.add(row)
    await db.flush()
    return row
