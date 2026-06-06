"""TutorTurnJob lifecycle service (L21a).

Wraps the DB row that ADR-0019 introduced. Three responsibilities:

1. **Create a turn** at POST time — inserts a `pending` row with
   reservation metadata + the prompt-template hash + an enqueue side-
   effect that fires after `commit()`.
2. **Atomic phase fence** — the Celery task's first action; UPDATE
   ... WHERE status='pending' RETURNING id, returning either the
   row (we own it) or None (another worker beat us).
3. **Terminal transitions** — `mark_complete`, `mark_failed`,
   `mark_aborted` — each zeros `reserved_cost_usd` so the sweep
   doesn't double-release.

The actual Redis Streams emit lives in `app/services/redis_streams.py`
and the Celery task itself in `app/workers/tasks/tutor_streaming.py`.
This module is pure DB.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.tutor_turn_job import (
    TERMINAL_TURN_STATUSES,
    TURN_STATUS_PENDING,
    TutorTurnJob,
)

log = get_logger(__name__)


async def count_active_turns_in_window(
    db: AsyncSession, *, user_id: str, window_seconds: int
) -> int:
    """COUNT the user's non-terminal turns created in the window.

    Gate-A fix: BYOK streamed turns skip the platform dollar reservation,
    so the enqueue path enforces the non-dollar BYOK request windows
    instead — terminal turns are visible to that count through their
    ``llm_calls`` rows (written by the worker at the terminal transition);
    this counts the in-flight remainder so an enqueue burst can't
    undercount. Index-covered by ``(user_id, created_at DESC)``.
    """
    from sqlalchemy import func, select

    stmt = select(func.count(TutorTurnJob.id)).where(
        TutorTurnJob.user_id == user_id,
        TutorTurnJob.status.notin_(TERMINAL_TURN_STATUSES),
        TutorTurnJob.created_at > func.now() - func.make_interval(0, 0, 0, 0, 0, 0, window_seconds),
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def create_turn(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str | None,
    reserved_cost_usd: Decimal,
    reservation_ip_key: str | None,
    prompt_template_hash: str | None = None,
    user_message: str | None = None,
    course_id: str | None = None,
    credential_id: str | None = None,
    enqueue_task: bool = True,
) -> TutorTurnJob:
    """Insert a new turn row.

    When ``enqueue_task=True`` (the default), an ``after_commit``
    listener on the underlying sync session fires the Celery task —
    via :func:`_safe_enqueue` so a broker outage doesn't 500 the
    POST handler (plan-v7 §V7-F6).

    L32 — ``user_message`` and ``course_id`` are persisted so the
    Celery task can run pgvector retrieval without a second
    round-trip to the POST body (which we don't keep).
    """
    turn = TutorTurnJob(
        user_id=user_id,
        conversation_id=conversation_id,
        course_id=course_id,
        user_message=user_message,
        status=TURN_STATUS_PENDING,
        reserved_cost_usd=reserved_cost_usd,
        reservation_ip_key=reservation_ip_key,
        prompt_template_hash=prompt_template_hash,
        # S5.12/R-S1'': the foreground-resolved credential id carried to the
        # worker (never the key — FR-BYOK-26).
        credential_id=credential_id,
    )
    db.add(turn)
    await db.flush()

    turn_id = turn.id
    if enqueue_task:
        _wire_enqueue_after_commit(db, turn_id=turn_id)

    return turn


def _wire_enqueue_after_commit(db: AsyncSession, *, turn_id: str) -> None:
    """Register a one-shot ``after_commit`` hook that enqueues the
    Celery task with broker-failure tolerance.

    The listener is attached to the underlying sync session (which is
    where SQLAlchemy event hooks live). We use ``once=True`` so a
    flushed-then-rolled-back session doesn't accidentally enqueue.
    """
    sync_session = db.sync_session

    def _safe_enqueue(*_a, **_kw):
        try:
            from app.workers.tasks.tutor_streaming import run_turn

            run_turn.delay(turn_id)
        except Exception as exc:
            # Broker down → the row stays `pending`; the sweep marks
            # it failed within 60s and the client's /status poll sees
            # a definitive failure. Far better than 5xx-ing the POST.
            log.error("tutor_celery_enqueue_failed", turn_id=turn_id, error=str(exc))

    event.listen(sync_session, "after_commit", _safe_enqueue, once=True)


async def claim_pending_turn(db: AsyncSession, turn_id: str) -> TutorTurnJob | None:
    """Atomic phase fence — promote pending → running. Idempotent.

    Returns the claimed row, or None if some other worker already
    claimed it (or the row is in a terminal state).
    """
    result = await db.execute(
        text(
            """
            UPDATE tutor_turn_jobs
            SET status = 'running', updated_at = NOW()
            WHERE id = :id AND status = 'pending'
            RETURNING id
            """
        ),
        {"id": turn_id},
    )
    claimed = result.fetchone()
    if claimed is None:
        return None
    # Re-fetch so the caller gets the full ORM row with reservation
    # metadata + user_id etc.
    return await _get_by_id(db, turn_id)


async def mark_terminal(
    db: AsyncSession,
    *,
    turn_id: str,
    status: str,
    error_code: str | None = None,
) -> bool:
    """Atomic transition to a terminal status. Zeros the reservation
    so the sweep doesn't try to release again.

    **Codex rescue (L21a-22 arc):** the WHERE clause refuses to
    overwrite an existing terminal status. Race scenario the rescue
    caught: a user calls DELETE → row goes ``aborted``; the still-
    running Celery worker then calls ``mark_terminal(..., complete)``
    on the same row. Without the non-terminal guard, the cancellation
    is silently overwritten and ``/status`` reports a clean turn.

    Returns ``True`` if the transition was applied, ``False`` if the
    row was already terminal. Callers should structlog the no-op so
    the race shows up in observability.
    """
    result = await db.execute(
        text(
            """
            UPDATE tutor_turn_jobs
            SET status = :status,
                error_code = :error_code,
                reserved_cost_usd = 0,
                updated_at = NOW()
            WHERE id = :id
              AND status NOT IN ('complete', 'failed', 'aborted')
            """
        ),
        {"id": turn_id, "status": status, "error_code": error_code},
    )
    return (result.rowcount or 0) > 0


async def abort_pending(db: AsyncSession, *, turn_id: str, error_code: str) -> bool:
    """Atomic pending→aborted transition (confirm-round-2 fix).

    Returns ``True`` iff THIS statement moved the row out of ``pending`` —
    the caller then owns the concurrency-slot release, because no worker
    ever claimed the turn (``claim_pending_turn`` requires
    ``status='pending'``) and none ever will. ``False`` means the row was
    already claimed or terminal: for a claimed turn the worker's
    ``finally`` owns the slot, and releasing from the API as well would
    double-decrement the Redis counter (the cap-bypass race Codex caught
    in the prior shape, which read the ORM status before mark_terminal).
    """
    result = await db.execute(
        text(
            """
            UPDATE tutor_turn_jobs
            SET status = 'aborted',
                error_code = :error_code,
                reserved_cost_usd = 0,
                updated_at = NOW()
            WHERE id = :id
              AND status = 'pending'
            """
        ),
        {"id": turn_id, "error_code": error_code},
    )
    return (result.rowcount or 0) > 0


async def set_reserved_cost(db: AsyncSession, *, turn_id: str, reserved_cost_usd) -> bool:
    """Record a reservation taken AFTER enqueue (confirm-round fix).

    A BYOK turn enqueues with ``reserved_cost_usd = 0``; when the worker
    discovers it must fall back to platform it reserves cost itself and
    stamps the row here so the cancel path and the sweep release the
    truth. Refuses terminal rows (same guard shape as ``mark_terminal``).
    """
    result = await db.execute(
        text(
            """
            UPDATE tutor_turn_jobs
            SET reserved_cost_usd = :reserved,
                updated_at = NOW()
            WHERE id = :id
              AND status NOT IN ('complete', 'failed', 'aborted')
            """
        ),
        {"id": turn_id, "reserved": reserved_cost_usd},
    )
    return (result.rowcount or 0) > 0


async def _get_by_id(db: AsyncSession, turn_id: str) -> TutorTurnJob | None:
    from sqlalchemy import select

    result = await db.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    return result.scalar_one_or_none()


async def get_turn_for_user(db: AsyncSession, *, turn_id: str, user_id: str) -> TutorTurnJob | None:
    """IDOR-safe read — only returns the row if it belongs to ``user_id``.

    Returning None on cross-user access is the IDOR safe shape
    (handler maps to 404, not 403, so the endpoint isn't a nanoid-
    existence oracle).
    """
    from sqlalchemy import select

    result = await db.execute(
        select(TutorTurnJob).where(
            TutorTurnJob.id == turn_id,
            TutorTurnJob.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def persist_stream_user_message(
    db: AsyncSession, *, conversation_id: str | None, content: str
) -> str | None:
    """Persist the learner's question for a streamed turn.

    Mirrors the non-streaming contract (``app/api/v1/tutor.py`` —
    "the user message is persisted before the LLM call so a network
    blip leaves a clean audit trail"): the worker calls this right
    after winning the claim fence, in the same transaction, so the
    question survives even if the provider dies mid-stream. No-op for
    conversation-less turns (the ``/demo`` synth-only path).

    Flush-only — the caller owns the commit boundary.
    """
    if not conversation_id or not content.strip():
        return None
    from app.models.tutor_conversation import TutorMessage, TutorMessageRole

    msg = TutorMessage(
        conversation_id=conversation_id,
        role=TutorMessageRole.user,
        content=content,
        citations=[],
    )
    db.add(msg)
    await db.flush()
    return msg.id


async def persist_stream_assistant_message(
    db: AsyncSession,
    *,
    conversation_id: str | None,
    content: str,
    citations: list[dict[str, str]],
) -> str | None:
    """Persist the streamed answer + bump the conversation's ordering.

    The streamed answer otherwise exists only as ephemeral
    ``synth_chunk`` events on a TTL'd Redis Stream — this is the row
    that makes history survive a reload and gives ``turn_complete`` a
    real ``message_id`` for the trace drill-down link. Also bumps
    ``last_message_at`` exactly like the non-streaming path
    (``app/api/v1/tutor.py``) so conversation lists order correctly.

    Flush-only — the caller owns the commit boundary.
    """
    if not conversation_id or not content.strip():
        return None
    from sqlalchemy import select

    from app.models.tutor_conversation import (
        TutorConversation,
        TutorMessage,
        TutorMessageRole,
    )

    msg = TutorMessage(
        conversation_id=conversation_id,
        role=TutorMessageRole.assistant,
        content=content,
        citations=citations,
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg)  # server_default created_at for the bump below

    conv = (
        await db.execute(select(TutorConversation).where(TutorConversation.id == conversation_id))
    ).scalar_one_or_none()
    if conv is not None:
        conv.last_message_at = msg.created_at
        await db.flush()
    return msg.id
