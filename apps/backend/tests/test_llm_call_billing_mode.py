"""S5.4 — llm_calls.billing_mode + quota_exceeded status literal.

Model-level assertions (additive; the pinned ``test_llm_call_log.py`` keeps
its existing coverage unchanged). DB round-trip runs at ``make test.api``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select

from app.models.llm_call import (
    BILLING_BYOK,
    BILLING_PLATFORM,
    STATUS_QUOTA_EXCEEDED,
    LLMCall,
)


def test_status_and_billing_literals() -> None:
    assert STATUS_QUOTA_EXCEEDED == "quota_exceeded"
    assert BILLING_PLATFORM == "platform"
    assert BILLING_BYOK == "byok"


def test_billing_mode_column_declared() -> None:
    col = {c.name: c for c in inspect(LLMCall).columns}["billing_mode"]
    assert col.nullable is False
    assert col.server_default is not None


def test_default_billing_mode_is_platform() -> None:
    # SQLAlchemy applies the python-side default at flush; assert the
    # declared default value so the column round-trips 'platform'.
    col = {c.name: c for c in inspect(LLMCall).columns}["billing_mode"]
    assert col.default.arg == "platform"


@pytest.mark.asyncio
async def test_byok_billing_mode_round_trips(db_session) -> None:
    row = LLMCall(
        user_id="u1",
        feature="tutor",
        provider="openai",
        model="gpt-4o-mini",
        latency_ms=10,
        status="ok",
        billing_mode=BILLING_BYOK,
    )
    db_session.add(row)
    await db_session.commit()
    fetched = (await db_session.execute(select(LLMCall).where(LLMCall.id == row.id))).scalar_one()
    assert fetched.billing_mode == "byok"
