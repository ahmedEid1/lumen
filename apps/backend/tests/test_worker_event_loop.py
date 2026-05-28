"""Regression: Celery prefork worker tasks survive a fresh event loop.

Prod incident (2026-05-28, surfaced the moment ``feature_tutor_streaming``
was flipped on): every tutor turn and the sweep beat crashed with
``RuntimeError: ... got Future ... attached to a different loop`` /
``RuntimeError: Event loop is closed``.

Root cause: worker task bodies run under a new ``asyncio.run()`` event
loop per invocation (ADR-0017), but reused the module-level *pooled*
async engine (``app.db.base.get_engine``), whose asyncpg connections
were bound to whichever loop first opened them. The second task onward
reused a connection on a foreign, already-closed loop.

Fix: each worker task gets its own ``NullPool`` engine created and
disposed inside its own loop — ``make_worker_engine`` /
``worker_session_scope``.

These tests run a worker body across two *independent* event loops in
one process — the exact prefork condition. They use throwaway loops
(not ``asyncio.run``) so the session-scoped ``event_loop`` fixture is
left untouched. The ``_engine`` fixture is requested so the schema
exists and (pre-fix) the module engine is bound to the session loop,
which is what made the very first foreign-loop run blow up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from app.db.base import worker_session_scope
from app.workers.tasks.tutor_sweep import _sweep_async


def _run_on_fresh_loop[T](coro_fn: Callable[[], Awaitable[T]]) -> T:
    """Run ``coro_fn`` on a brand-new event loop, the way a Celery
    prefork task's ``asyncio.run()`` does — without disturbing the
    session-scoped ``event_loop`` fixture's loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()


def test_sweep_survives_repeated_event_loops(_engine) -> None:
    """Two sweeps on two distinct loops == two prefork task runs.

    Against an empty ``tutor_turn_jobs`` table the sweep is a no-op that
    touches Postgres only (no Redis round-trip), so this is a tight,
    dependency-light guard. Pre-fix the second run — and, because
    conftest binds the module engine to the session loop, the first —
    raised the cross-loop ``RuntimeError``.
    """
    _run_on_fresh_loop(_sweep_async)
    _run_on_fresh_loop(_sweep_async)


def test_worker_session_scope_across_loops(_engine) -> None:
    """The per-task scope opens + disposes its own engine each loop, so
    a real query succeeds on two independent loops back to back."""

    async def _touch() -> int:
        async with worker_session_scope() as Session, Session() as db:
            return (await db.execute(text("SELECT 1"))).scalar_one()

    assert _run_on_fresh_loop(_touch) == 1
    assert _run_on_fresh_loop(_touch) == 1
