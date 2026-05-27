"""Codex rescue regression: a cancelled tutor turn must not get
silently overwritten by a late worker completion.

Race scenario:
  t0: user POST /tutor/turns           → row 'pending', task enqueued
  t1: Celery worker claims it          → row 'running'
  t2: user DELETE /tutor/turns/{tid}   → mark_terminal(..., 'aborted')
                                         row 'aborted' (terminal)
  t3: worker finishes orchestration    → mark_terminal(..., 'complete')

Before the rescue fix, t3 overwrites the 'aborted' status with
'complete'; the /status endpoint then lies. After the fix,
``mark_terminal`` refuses to transition out of a terminal status
and returns False so the worker can log the no-op.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tutor_turn_job import (
    TURN_STATUS_ABORTED,
    TURN_STATUS_COMPLETE,
    TURN_STATUS_PENDING,
    TutorTurnJob,
)
from app.services.tutor_turn_service import mark_terminal


async def _make_pending_turn(db_session: AsyncSession, user_id: str) -> str:
    turn = TutorTurnJob(
        user_id=user_id,
        conversation_id=None,
        status=TURN_STATUS_PENDING,
    )
    db_session.add(turn)
    await db_session.commit()
    return turn.id


async def test_mark_terminal_first_call_succeeds(db_session: AsyncSession, make_user) -> None:
    user = await make_user(email="rescue-1@lumen.test")
    turn_id = await _make_pending_turn(db_session, user.id)

    applied = await mark_terminal(
        db_session,
        turn_id=turn_id,
        status=TURN_STATUS_ABORTED,
        error_code="tutor.cancelled_by_user",
    )
    await db_session.commit()
    assert applied is True


async def test_mark_terminal_does_not_overwrite_aborted_with_complete(
    db_session: AsyncSession, make_user
) -> None:
    """The critical regression. After DELETE → aborted, a late worker
    `mark_terminal(complete)` must be refused; the row stays
    `aborted`, the API returns False so the worker can log it."""
    user = await make_user(email="rescue-2@lumen.test")
    turn_id = await _make_pending_turn(db_session, user.id)

    # t2 — user cancels.
    await mark_terminal(
        db_session,
        turn_id=turn_id,
        status=TURN_STATUS_ABORTED,
        error_code="tutor.cancelled_by_user",
    )
    await db_session.commit()

    # t3 — worker finishes, tries to mark complete.
    applied = await mark_terminal(
        db_session,
        turn_id=turn_id,
        status=TURN_STATUS_COMPLETE,
    )
    await db_session.commit()
    assert applied is False, "mark_terminal must refuse to overwrite an existing terminal status"

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one()
    assert turn.status == TURN_STATUS_ABORTED


async def test_mark_terminal_idempotent_on_same_status(db_session: AsyncSession, make_user) -> None:
    """Even a re-call with the same terminal status is refused — the
    row is already terminal, nothing to apply. Returning False is
    the right contract (the caller logs the no-op)."""
    user = await make_user(email="rescue-3@lumen.test")
    turn_id = await _make_pending_turn(db_session, user.id)

    await mark_terminal(db_session, turn_id=turn_id, status=TURN_STATUS_COMPLETE)
    await db_session.commit()

    applied = await mark_terminal(db_session, turn_id=turn_id, status=TURN_STATUS_COMPLETE)
    await db_session.commit()
    assert applied is False
