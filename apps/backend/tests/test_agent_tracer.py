"""``agent_tracer.record_step`` — write, tree-traversal, isolation.

Lumen v2 Phase H7. The tracer is the substrate I2 (multi-agent
tutor) and I3 (self-critique authoring) write into. These tests
pin the persistence shape, the tree-traversal helper, and the
SAVEPOINT-isolated write semantics that mirror H1's cost-meter
guarantee — a trace-write hiccup must not poison the outer
transaction.

We import the model module at the top so the test collection
phase registers ``agent_traces`` with ``Base.metadata`` before
the session-scoped ``_engine`` fixture runs ``create_all``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# Import the model module so ``Base.metadata`` picks up the table
# before ``_engine`` calls ``create_all``. This stays load-bearing
# until ``app.models.__init__`` re-exports the model (orchestrator
# follow-up).
from app.models import agent_trace as _agent_trace_module  # noqa: F401
from app.models.agent_trace import (
    TRACE_STATUS_ERROR,
    TRACE_STATUS_OK,
    AgentTrace,
)
from app.services.agent_tracer import (
    list_recent,
    list_traces_for_call,
    record_step,
)


def _uid() -> str:
    """Unique pseudo user id per test — tracer's ``user_id`` doesn't FK."""
    return f"u-{uuid.uuid4().hex[:16]}"


# ---------- Happy path ----------


async def test_record_step_persists_row_with_expected_fields(
    db_session: AsyncSession,
) -> None:
    """One ``record_step`` → one row with payload + status + duration intact."""
    user_id = _uid()
    payload = {"prompt": "Solve x+1=2", "model": "claude-sonnet-4-5"}
    trace = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="plan",
        step_index=0,
        payload=payload,
        duration_ms=42,
        status=TRACE_STATUS_OK,
    )
    assert trace is not None
    assert trace.feature == "tutor.multi_agent"
    assert trace.step == "plan"
    assert trace.step_index == 0
    assert trace.status == TRACE_STATUS_OK
    assert trace.duration_ms == 42
    assert trace.payload == payload
    assert trace.id is not None  # nanoid PK populated

    # Round-trip — re-read from the DB to confirm the row landed.
    fetched = (
        await db_session.execute(select(AgentTrace).where(AgentTrace.id == trace.id))
    ).scalar_one()
    assert fetched.payload == payload
    assert fetched.user_id == user_id


async def test_record_step_defaults_empty_payload_to_object(
    db_session: AsyncSession,
) -> None:
    """``payload=None`` → ``{}`` (NOT NULL on the JSONB column)."""
    trace = await record_step(
        db_session,
        user_id=_uid(),
        feature="tutor",
        step="tool_call",
        step_index=0,
        payload=None,
    )
    assert trace is not None
    assert trace.payload == {}


async def test_record_step_records_error_status(
    db_session: AsyncSession,
) -> None:
    """An error step persists ``status="error"`` and the error payload."""
    trace = await record_step(
        db_session,
        user_id=_uid(),
        feature="tutor.multi_agent",
        step="sub_agent.retriever",
        step_index=1,
        payload={"error_kind": "TimeoutError", "message": "upstream slow"},
        status=TRACE_STATUS_ERROR,
        duration_ms=5000,
    )
    assert trace is not None
    assert trace.status == TRACE_STATUS_ERROR
    assert trace.payload["error_kind"] == "TimeoutError"


# ---------- Tree shape ----------


async def test_record_step_threads_parent_trace_id_for_tree(
    db_session: AsyncSession,
) -> None:
    """Children carry ``parent_trace_id`` and traverse back to the root."""
    user_id = _uid()
    root = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="plan",
        step_index=0,
        payload={"goal": "explain backprop"},
    )
    assert root is not None
    child_a = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="sub_agent.retriever",
        step_index=1,
        parent_trace_id=root.id,
        payload={"query": "backprop chain rule"},
    )
    child_b = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="sub_agent.web_searcher",
        step_index=2,
        parent_trace_id=root.id,
        payload={"query": "backprop intuition"},
    )
    grandchild = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="tool_call",
        step_index=0,
        parent_trace_id=child_a.id if child_a else None,
        payload={"tool_name": "search_chunks"},
    )
    assert child_a is not None
    assert child_b is not None
    assert grandchild is not None

    # Walk up from the grandchild to the root via ``parent_trace_id``.
    pointer: str | None = grandchild.parent_trace_id
    seen: list[str] = []
    while pointer is not None:
        row = (
            await db_session.execute(select(AgentTrace).where(AgentTrace.id == pointer))
        ).scalar_one()
        seen.append(row.id)
        pointer = row.parent_trace_id
    assert seen == [child_a.id, root.id]


async def test_list_traces_for_call_returns_tree_in_order(
    db_session: AsyncSession,
) -> None:
    """``list_traces_for_call`` filters by ``parent_call_id`` and stable-sorts.

    We don't seed a real ``llm_calls`` row — ``parent_call_id`` is
    nullable and the FK is ``ON DELETE SET NULL``, so we pass a
    string id that doesn't have to exist. The tracer's tests cover
    the trace shape; the FK is tested implicitly by the admin API
    test which fetches via a real call id.
    """
    # parent_call_id has an FK to llm_calls — use NULL here so we
    # don't need to seed an unrelated row, and assert behaviour by
    # filtering on NULL via a direct query rather than the helper
    # (the helper compares to a specific id).
    user_id = _uid()
    fake_call_id = f"call-{uuid.uuid4().hex[:16]}"

    # Seed a fake llm_calls row so the FK holds. Using the model
    # directly avoids the cost-meter wrapper.
    from decimal import Decimal

    from app.models.llm_call import STATUS_OK, LLMCall

    db_session.add(
        LLMCall(
            id=fake_call_id,
            user_id=user_id,
            feature="tutor.multi_agent",
            provider="anthropic",
            model="claude-sonnet-4-5",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=Decimal("0.000010"),
            latency_ms=100,
            status=STATUS_OK,
            error_kind=None,
        )
    )
    await db_session.flush()

    # Three steps linked to that call.
    step_a = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="plan",
        step_index=0,
        parent_call_id=fake_call_id,
        payload={},
    )
    step_b = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="sub_agent.retriever",
        step_index=1,
        parent_call_id=fake_call_id,
        parent_trace_id=step_a.id if step_a else None,
        payload={},
    )
    step_c = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="critic",
        step_index=2,
        parent_call_id=fake_call_id,
        parent_trace_id=step_a.id if step_a else None,
        payload={},
    )
    assert step_a and step_b and step_c

    rows = await list_traces_for_call(db_session, fake_call_id)
    assert len(rows) == 3
    # Stable order: created_at ASC, then step_index ASC. The three
    # rows were inserted in order, so the IDs should come back in
    # insertion order.
    assert [r.id for r in rows] == [step_a.id, step_b.id, step_c.id]


# ---------- list_recent ----------


async def test_list_recent_filters_by_feature(db_session: AsyncSession) -> None:
    """``feature=`` filter narrows the result set."""
    user_id = _uid()
    await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="plan",
        step_index=0,
        payload={},
    )
    await record_step(
        db_session,
        user_id=user_id,
        feature="authoring.critique_revise",
        step="critic",
        step_index=0,
        payload={},
    )
    rows = await list_recent(db_session, feature="authoring.critique_revise", user_id=user_id)
    assert len(rows) == 1
    assert rows[0].feature == "authoring.critique_revise"


async def test_list_recent_orders_newest_first(db_session: AsyncSession) -> None:
    """Newest row comes first regardless of insertion order."""
    user_id = _uid()
    first = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor",
        step="plan",
        step_index=0,
        payload={"seq": "first"},
    )
    second = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor",
        step="critic",
        step_index=0,
        payload={"seq": "second"},
    )
    assert first and second
    rows = await list_recent(db_session, user_id=user_id, limit=10)
    # The two rows we inserted should be present and the most recent
    # one (``second``) should lead.
    ids = [r.id for r in rows]
    assert second.id in ids
    assert first.id in ids
    assert ids.index(second.id) < ids.index(first.id)


# ---------- SAVEPOINT isolation ----------


async def test_record_step_failure_does_not_poison_outer_transaction(
    db_session: AsyncSession,
) -> None:
    """A trace-write SQLAlchemyError mustn't roll back the outer txn.

    Mirrors H1's ``_persist_row`` contract. We force the inner
    INSERT to fail by stubbing ``session.begin_nested`` to raise
    ``SQLAlchemyError`` partway through; the outer session must
    still be usable for the next operation.
    """
    user_id = _uid()
    # Seed a row through normal channels to confirm the outer txn
    # is live and accepting writes.
    seeded = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor",
        step="plan",
        step_index=0,
        payload={},
    )
    assert seeded is not None

    # Now monkeypatch the session so the next begin_nested raises.
    # We use a lightweight context-manager substitute that raises
    # on __aenter__ — that's the same surface ``async with
    # db.begin_nested()`` hits.
    original_begin_nested = db_session.begin_nested

    class _BoomCtx:
        async def __aenter__(self):
            raise SQLAlchemyError("simulated DB hiccup")

        async def __aexit__(self, *_: object) -> None:  # pragma: no cover
            return None

    db_session.begin_nested = lambda: _BoomCtx()  # type: ignore[method-assign]
    try:
        result = await record_step(
            db_session,
            user_id=user_id,
            feature="tutor",
            step="critic",
            step_index=1,
            payload={"will": "fail"},
        )
        # The failure path returns ``None`` rather than raising —
        # callers see "trace not recorded" but keep running.
        assert result is None
    finally:
        db_session.begin_nested = original_begin_nested  # type: ignore[method-assign]

    # Outer transaction is still alive — we can write another row.
    follow_up = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor",
        step="reviser",
        step_index=2,
        payload={"after": "hiccup"},
    )
    assert follow_up is not None
    assert follow_up.payload == {"after": "hiccup"}

    # The seeded row is still readable, confirming the outer txn
    # wasn't rolled back.
    rows = (
        (await db_session.execute(select(AgentTrace).where(AgentTrace.user_id == user_id)))
        .scalars()
        .all()
    )
    ids = {r.id for r in rows}
    assert seeded.id in ids
    assert follow_up.id in ids
