"""Idempotency-key reserve/lookup/finalize helper (ADR-0028 §Decision.2, S4.6).

Clone is the first endpoint to honor ``Idempotency-Key`` (ADR-0028 §Consequences),
seeding this infrastructure for the rest of v1.

The S4-gate hardening (Codex-C2 / Gate-B B3) inverts the original add-after-
materialize order to a **reserve-then-materialize** contract so a concurrent
same-key double-submit can never (a) raise an unhandled ``IntegrityError`` on the
loser or (b) torn-write two clones:

* :func:`reserve` — INSERT the key row FIRST (``response_target_id`` NULL) inside
  a ``begin_nested`` savepoint. Returns a small result discriminating three
  outcomes: ``reserved`` (we won — caller materializes then calls
  :func:`finalize`), ``replay`` (a prior live key already has a committed result
  → caller returns that course id), or ``in_flight`` (the winner reserved but
  hasn't committed yet → caller raises ``clone.in_progress`` 409). The savepoint
  is rolled back on the constraint loss so the outer transaction stays usable.
* :func:`finalize` — UPDATE the reserved row's ``response_target_id`` to the
  committed result id. Rides the caller's transaction so a rolled-back clone
  leaves the reservation row uncommitted too (the key is free to retry).
* :func:`lookup` — read-only convenience returning the live
  ``response_target_id`` for ``(user_id, key, endpoint)`` (NULL-or-expired ⇒
  None). Kept for callers that only need a replay read.

The 24h TTL bounds replay; :func:`sweep_expired` (driven by the beat schedule)
reclaims expired rows via the ``ix_idempotency_keys_created_at`` index.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency import IdempotencyKey

#: Replay window for clone (ADR-0028 §Decision.2 — 24h TTL).
CLONE_IDEMPOTENCY_TTL = timedelta(hours=24)


class ReserveOutcome(enum.StrEnum):
    """Discriminates the three reserve-then-materialize branches."""

    #: We inserted the row; caller materializes the result then calls finalize.
    RESERVED = "reserved"
    #: A prior live key already points at a committed result; caller replays it.
    REPLAY = "replay"
    #: The winning reservation exists but has not committed its result yet;
    #: caller must raise ``clone.in_progress`` (409) — no torn state.
    IN_FLIGHT = "in_flight"


@dataclass(slots=True)
class Reservation:
    outcome: ReserveOutcome
    #: The reserved key id (RESERVED) — passed to :func:`finalize`.
    key_id: str | None = None
    #: The prior committed result id (REPLAY).
    response_target_id: str | None = None


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


async def reserve(
    db: AsyncSession,
    *,
    user_id: str,
    key: str,
    endpoint: str,
    ttl: timedelta = CLONE_IDEMPOTENCY_TTL,
) -> Reservation:
    """Reserve ``(user_id, key, endpoint)`` BEFORE materializing the result.

    Inserts the key row with a NULL ``response_target_id`` inside a
    ``begin_nested`` savepoint. Three outcomes:

    * ``RESERVED`` — the INSERT won; the caller owns materialization and must
      call :func:`finalize` with the committed result id.
    * ``REPLAY`` — the INSERT lost the unique-constraint race AND the winning row
      already carries a committed ``response_target_id``: the caller returns that
      id (the standard replay).
    * ``IN_FLIGHT`` — the INSERT lost but the winner has not committed its result
      yet (NULL target): the caller raises ``clone.in_progress`` (409).

    The savepoint isolates the IntegrityError so the OUTER transaction stays
    usable for the replay/in-flight lookup that follows.
    """
    row = IdempotencyKey(
        user_id=user_id,
        idempotency_key=key,
        endpoint=endpoint,
        response_target_id=None,
        expires_at=datetime.now(UTC) + ttl,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Lost the race — resolve to the winner inside the (still-usable) outer
        # txn. FOR UPDATE (confirm-round-3 fix): ownership of the key row must
        # be acquired ATOMICALLY — without the row lock, two same-key retries
        # could both read an expired/vanished state before either committed,
        # both take RESERVED, and both materialize (duplicate clones — the
        # exact regression the takeover/rebind paths were built to prevent).
        # The lock is held to the end of THIS request's transaction, so a
        # concurrent contender blocks here and then re-reads committed state:
        # a refreshed reservation → IN_FLIGHT, a stamped target → REPLAY.
        # Single-row, single-order acquisition → no deadlock surface.
        winner = (
            await db.execute(
                select(IdempotencyKey)
                .where(
                    IdempotencyKey.user_id == user_id,
                    IdempotencyKey.idempotency_key == key,
                    IdempotencyKey.endpoint == endpoint,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if winner is None:
            # Pathological (winner deleted between conflict and lookup) —
            # treat the key as free: re-reserve via recursion-free retry.
            return Reservation(outcome=ReserveOutcome.IN_FLIGHT)
        if winner.expires_at <= datetime.now(UTC):
            # Confirm-round-2 fix: an EXPIRED row lingering before the hourly
            # sweep must not replay a stale result (or 409 on a dead
            # reservation) — the TTL contract says the key is reusable.
            # Take the row over in place: fresh TTL, target cleared, caller
            # owns materialization (finalize stamps this same row).
            winner.response_target_id = None
            winner.expires_at = datetime.now(UTC) + ttl
            await db.flush()
            return Reservation(outcome=ReserveOutcome.RESERVED, key_id=winner.id)
        if winner.response_target_id is not None:
            return Reservation(
                outcome=ReserveOutcome.REPLAY,
                response_target_id=winner.response_target_id,
                key_id=winner.id,
            )
        # Winner reserved but its result has not committed yet → honest 409.
        return Reservation(outcome=ReserveOutcome.IN_FLIGHT)

    return Reservation(outcome=ReserveOutcome.RESERVED, key_id=row.id)


async def rebind(db: AsyncSession, *, key_id: str, ttl: timedelta = CLONE_IDEMPOTENCY_TTL) -> None:
    """Re-own an existing key row whose committed target has vanished.

    Confirm-round-2 fix: a REPLAY row pointing at a hard-deleted result must
    be rebound (target cleared, TTL refreshed) BEFORE the caller materializes
    anew, so :func:`finalize` stamps THIS row and concurrent same-key
    requests see IN_FLIGHT — otherwise every retry minted another result
    until the sweep ran.
    """
    row = await db.get(IdempotencyKey, key_id)
    if row is not None:
        row.response_target_id = None
        row.expires_at = datetime.now(UTC) + ttl
        await db.flush()


async def finalize(db: AsyncSession, *, key_id: str, response_target_id: str) -> None:
    """Stamp the reserved row with the committed result id.

    Rides the caller's transaction so a rolled-back clone leaves the reservation
    uncommitted too (the key stays free to retry — FR-CLONE-20/22).
    """
    row = await db.get(IdempotencyKey, key_id)
    if row is not None:
        row.response_target_id = response_target_id
        await db.flush()


async def sweep_expired(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete idempotency rows past their ``expires_at`` (TTL sweep).

    Returns the number reclaimed. The ``ix_idempotency_keys_created_at`` index is
    the cheap age helper this complements; expiry is the authoritative window.
    """
    cutoff = now or datetime.now(UTC)
    result = await db.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at <= cutoff))
    return int(result.rowcount or 0)
