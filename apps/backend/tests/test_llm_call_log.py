"""``call_logged`` — persist a row, trip the budget guard, capture errors.

The wrapper is the only entrypoint metered LLM traffic flows through,
so every codepath has a test here: success persists the right
columns, failure persists an error row + re-raises, and an
already-spent user gets a ``BudgetExceededError`` (with a sentinel
row still hitting the table so the admin sees the spike).

Tests use the ``Noop`` provider for the happy path so we don't burn
tokens; the error / budget paths use a tiny inline provider that
either raises or returns a controlled response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import BudgetExceededError
from app.models.llm_call import (
    STATUS_BUDGET_EXCEEDED,
    STATUS_ERROR,
    STATUS_OK,
    LLMCall,
)
from app.services.llm import ChatMessage, ChatResponse, NoopProvider
from app.services.llm_call_log import call_logged


# ---------- Helpers ----------


@pytest.fixture(autouse=True)
def _settings_overrides(monkeypatch):
    """Enable cost tracking + give the budget guard a known cap.

    ``$1.00 / 24h`` matches the prod default but is tight enough that
    a single seeded $1+ row pushes the guard over the line.
    """
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "1.00")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _msgs(text: str = "Hello") -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


class _FailingProvider:
    """Inline provider that always raises — exercises the error path."""

    name = "noop"
    _model = "noop-fail"

    async def chat(self, messages, temperature=0.2):  # pragma: no cover - via chat_with_usage
        return await self.chat_with_usage(messages, temperature)

    async def chat_with_usage(self, messages, temperature=0.2):
        raise RuntimeError("upstream model exploded")


class _FixedUsageProvider:
    """Returns a controlled ChatResponse so we can pin token math.

    Used in the success-path test where we want to know exactly what
    ``compute_cost_usd`` will receive.
    """

    name = "openai"
    _model = "llama-3.3-70b-versatile"

    async def chat(self, messages, temperature=0.2):  # pragma: no cover
        return "hi"

    async def chat_with_usage(self, messages, temperature=0.2):
        return ChatResponse(
            text="hi",
            prompt_tokens=100,
            completion_tokens=50,
            model="llama-3.3-70b-versatile",
        )


def _make_user_id() -> str:
    """Fabricate a unique pseudo user id for budget-guard tests.

    The metered ``user_id`` column doesn't FK to ``users`` — see the
    model's docstring — so we don't actually need a real ``users``
    row, just an unambiguous string per test.
    """
    return f"u-{uuid.uuid4().hex[:16]}"


async def _seed_spend(
    db: AsyncSession,
    *,
    user_id: str,
    cost: Decimal,
    when: datetime | None = None,
) -> None:
    """Drop one fake ``llm_calls`` row to push a user over budget."""
    row = LLMCall(
        user_id=user_id,
        feature="tutor",
        provider="openai",
        model="llama-3.3-70b-versatile",
        prompt_tokens=1000,
        completion_tokens=1000,
        cost_usd=cost,
        latency_ms=100,
        status=STATUS_OK,
        error_kind=None,
    )
    if when is not None:
        row.created_at = when
    db.add(row)
    await db.flush()


# ---------- Happy path ----------


async def test_call_logged_persists_ok_row_with_cost(
    db_session: AsyncSession,
) -> None:
    """Successful call → one row with status=ok, tokens, cost, latency."""
    user_id = _make_user_id()
    response = await call_logged(
        _FixedUsageProvider(),
        _msgs(),
        user_id=user_id,
        feature="tutor",
        session=db_session,
    )
    await db_session.flush()
    assert response.text == "hi"

    row = (
        await db_session.execute(
            select(LLMCall).where(LLMCall.user_id == user_id)
        )
    ).scalar_one()
    assert row.status == STATUS_OK
    assert row.error_kind is None
    assert row.feature == "tutor"
    assert row.provider == "openai"
    assert row.model == "llama-3.3-70b-versatile"
    assert row.prompt_tokens == 100
    assert row.completion_tokens == 50
    # 0.59 * 100 / 1e6 + 0.79 * 50 / 1e6 = 0.000059 + 0.0000395 = 0.0000985.
    # Quantized to 6 decimals via banker's rounding (the Decimal default),
    # this rounds to 0.000098 — pin that exact value so a future change to
    # the rounding mode trips the test loudly rather than silently shifting
    # the persisted cost.
    assert row.cost_usd == Decimal("0.000098")
    # Latency is wall-clock and the noop returns sub-ms; assert
    # only the lower bound so a fast CI box doesn't fail spuriously.
    assert row.latency_ms >= 0


async def test_call_logged_with_noop_provider_uses_estimated_tokens(
    db_session: AsyncSession,
) -> None:
    """Noop provider → tokens estimated via ``len // 4``."""
    user_id = _make_user_id()
    await call_logged(
        NoopProvider(),
        [ChatMessage(role="system", content="Lesson Labc: T\nbody"),
         ChatMessage(role="user", content="What?")],
        user_id=user_id,
        feature="tutor",
        session=db_session,
    )
    await db_session.flush()
    row = (
        await db_session.execute(
            select(LLMCall).where(LLMCall.user_id == user_id)
        )
    ).scalar_one()
    assert row.status == STATUS_OK
    assert row.prompt_tokens > 0
    assert row.completion_tokens > 0
    # Unknown ("noop") model → $0 cost (with a warning logged elsewhere).
    assert row.cost_usd == Decimal("0")


# ---------- Error path ----------


async def test_call_logged_persists_error_row_and_reraises(
    db_session: AsyncSession,
) -> None:
    """Provider raises → row with status=error, error_kind = class name."""
    user_id = _make_user_id()
    with pytest.raises(RuntimeError, match="upstream model exploded"):
        await call_logged(
            _FailingProvider(),
            _msgs(),
            user_id=user_id,
            feature="tutor",
            session=db_session,
        )
    await db_session.flush()
    row = (
        await db_session.execute(
            select(LLMCall).where(LLMCall.user_id == user_id)
        )
    ).scalar_one()
    assert row.status == STATUS_ERROR
    assert row.error_kind == "RuntimeError"
    assert row.prompt_tokens == 0
    assert row.completion_tokens == 0


# ---------- Budget guard ----------


async def test_budget_guard_trips_when_spend_over_cap(
    db_session: AsyncSession,
) -> None:
    """Pre-seed a row at $2 → next call → BudgetExceededError + sentinel row.

    The cap is $1 per the fixture; $2 of prior spend pushes the guard
    over without ambiguity. We then assert exactly two rows exist for
    this user: the seed row and the "blocked" sentinel.
    """
    user_id = _make_user_id()
    await _seed_spend(db_session, user_id=user_id, cost=Decimal("2.000000"))

    with pytest.raises(BudgetExceededError) as exc_info:
        await call_logged(
            _FixedUsageProvider(),
            _msgs(),
            user_id=user_id,
            feature="tutor",
            session=db_session,
        )
    assert "Daily LLM budget" in str(exc_info.value)

    await db_session.flush()
    rows = (
        await db_session.execute(
            select(LLMCall)
            .where(LLMCall.user_id == user_id)
            .order_by(LLMCall.created_at)
        )
    ).scalars().all()
    assert len(rows) == 2
    statuses = {r.status for r in rows}
    assert STATUS_OK in statuses
    assert STATUS_BUDGET_EXCEEDED in statuses


async def test_budget_guard_ignores_spend_outside_window(
    db_session: AsyncSession,
) -> None:
    """A $5 row from 48h ago doesn't count — call should succeed.

    Proves the window is rolling rather than calendar-bound. The seed
    row is placed two days in the past so the 24h sum stays empty.
    """
    user_id = _make_user_id()
    await _seed_spend(
        db_session,
        user_id=user_id,
        cost=Decimal("5.000000"),
        when=datetime.now(UTC) - timedelta(hours=48),
    )
    response = await call_logged(
        _FixedUsageProvider(),
        _msgs(),
        user_id=user_id,
        feature="tutor",
        session=db_session,
    )
    assert response.text == "hi"


async def test_budget_guard_skipped_for_system_sentinel(
    db_session: AsyncSession,
) -> None:
    """The ``__system__`` user id isn't gated by the per-user budget.

    Eval suite + ingest pipelines run under the sentinel id; the
    operator throttles them via dedicated knobs (Phase H2 / H4), not
    the per-user 24h cap.
    """
    from app.models.llm_call import SYSTEM_USER_ID

    # Even with an absurdly large pre-existing spend on the sentinel,
    # the next call must go through.
    await _seed_spend(
        db_session, user_id=SYSTEM_USER_ID, cost=Decimal("999.000000")
    )
    response = await call_logged(
        _FixedUsageProvider(),
        _msgs(),
        user_id=SYSTEM_USER_ID,
        feature="eval.judge",
        session=db_session,
    )
    assert response.text == "hi"


# ---------- Disable switch ----------


async def test_cost_tracking_disabled_skips_meter(
    db_session: AsyncSession, monkeypatch
) -> None:
    """``LLM_COST_TRACKING_ENABLED=false`` → no row written, no guard."""
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    user_id = _make_user_id()
    # Seed enough spend to trip the guard if it ran — the disabled
    # path should sail past without checking.
    await _seed_spend(db_session, user_id=user_id, cost=Decimal("100.000000"))

    response = await call_logged(
        _FixedUsageProvider(),
        _msgs(),
        user_id=user_id,
        feature="tutor",
        session=db_session,
    )
    assert response.text == "hi"

    # Exactly one row in the table for this user (the seed; the call
    # itself didn't write).
    await db_session.flush()
    rows = (
        await db_session.execute(
            select(LLMCall).where(LLMCall.user_id == user_id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].cost_usd == Decimal("100.000000")
