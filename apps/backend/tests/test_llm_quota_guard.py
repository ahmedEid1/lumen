"""S5.8 — pre-dispatch DB COUNT request quota (DR-11/16) + concurrency lease.

DB-backed (runs at make test.api). The core assertion: a $0 BYOK call STILL
counts toward the request quota and trips it; the provider is never invoked
when over-limit; a sentinel ``quota_exceeded`` row is persisted; SYSTEM
bypasses; Redis-down fails open.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import get_settings
from app.core.errors import QuotaExceededError
from app.models.llm_call import (
    BILLING_BYOK,
    STATUS_OK,
    STATUS_QUOTA_EXCEEDED,
    SYSTEM_USER_ID,
    LLMCall,
)
from app.services.llm import ChatMessage, ChatResponse
from app.services.llm_call_log import call_logged


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")  # high — isolate the request guard
    monkeypatch.setenv("LLM_USER_REQUEST_QUOTA_24H", "2")
    monkeypatch.setenv("LLM_USER_REQUEST_QUOTA_1H", "100")
    monkeypatch.setenv("BYOK_REQUESTS_24H", "2")
    # No working Redis in unit env — leasing must fail-open.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6390/15")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _uid() -> str:
    return f"u-{uuid.uuid4().hex[:16]}"


def _msgs() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hi")]


class _SpyProvider:
    """Records whether it was invoked; reports a $0-cost (unpriced) model."""

    name = "openai"
    _model = "free-model-not-in-pricing"

    def __init__(self) -> None:
        self.invoked = 0

    async def chat(self, messages, temperature=0.2):  # pragma: no cover
        return await self.chat_with_usage(messages, temperature)

    async def chat_with_usage(self, messages, temperature=0.2):
        self.invoked += 1
        return ChatResponse(
            text="ok",
            prompt_tokens=1,
            completion_tokens=1,
            model="free-model-not-in-pricing",
        )


async def _count(db, user_id, status=None) -> int:
    from sqlalchemy import func, select

    stmt = select(func.count(LLMCall.id)).where(LLMCall.user_id == user_id)
    if status is not None:
        stmt = stmt.where(LLMCall.status == status)
    return int((await db.execute(stmt)).scalar_one())


@pytest.mark.asyncio
async def test_byok_zero_cost_call_still_counts_and_trips(db_session) -> None:
    """Core DR-16: a $0 BYOK model still counts; the 3rd call trips."""
    uid = _uid()
    p = _SpyProvider()
    # quota 24h = 2. Two calls succeed.
    for _ in range(2):
        await call_logged(
            p, _msgs(), user_id=uid, feature="tutor", session=db_session, billing_mode=BILLING_BYOK
        )
        await db_session.commit()
    assert p.invoked == 2
    assert await _count(db_session, uid, STATUS_OK) == 2

    # 3rd is over-limit → QuotaExceededError, provider NOT invoked, sentinel row.
    with pytest.raises(QuotaExceededError) as ei:
        await call_logged(
            p, _msgs(), user_id=uid, feature="tutor", session=db_session, billing_mode=BILLING_BYOK
        )
    assert p.invoked == 2, "provider must NOT be invoked when over quota"
    assert ei.value.details["dimension"] == "requests_24h"
    await db_session.commit()
    assert await _count(db_session, uid, STATUS_QUOTA_EXCEEDED) == 1
    # The sentinel row is attributed to byok.
    from sqlalchemy import select

    sentinel = (
        await db_session.execute(
            select(LLMCall).where(LLMCall.user_id == uid, LLMCall.status == STATUS_QUOTA_EXCEEDED)
        )
    ).scalar_one()
    assert sentinel.billing_mode == "byok"


@pytest.mark.asyncio
async def test_system_user_bypasses_quota(db_session) -> None:
    p = _SpyProvider()
    for _ in range(5):
        await call_logged(p, _msgs(), user_id=SYSTEM_USER_ID, feature="eval", session=db_session)
        await db_session.commit()
    assert p.invoked == 5  # never throttled


@pytest.mark.asyncio
async def test_platform_call_records_platform_billing_mode(db_session) -> None:
    uid = _uid()
    p = _SpyProvider()
    await call_logged(p, _msgs(), user_id=uid, feature="tutor", session=db_session)
    await db_session.commit()
    from sqlalchemy import select

    row = (await db_session.execute(select(LLMCall).where(LLMCall.user_id == uid))).scalar_one()
    assert row.billing_mode == "platform"


@pytest.mark.asyncio
async def test_redis_down_fails_open(db_session) -> None:
    """Concurrency lease points at a dead Redis → the call still proceeds."""
    uid = _uid()
    p = _SpyProvider()
    resp = await call_logged(p, _msgs(), user_id=uid, feature="tutor", session=db_session)
    await db_session.commit()
    assert resp.text == "ok"
    assert p.invoked == 1  # the DB guard is the hard one; Redis-down is fail-open
