"""S5.13 — admin cost surface: billing_mode grouping + platform-$ excludes BYOK.

DB-backed (runs at make test.api). Seeds mixed platform + byok rows and
asserts the admin summary's total_cost_usd excludes byok rows, that the
by_billing_mode grouping surfaces BYOK adoption/usage, and that the list view
never leaks key material.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import admin_llm_calls
from app.models.llm_call import STATUS_OK, LLMCall
from app.models.user import Role


@pytest.fixture
async def admin_app(app):
    app.include_router(admin_llm_calls.router, prefix="/api/v1/admin", tags=["admin"])
    return app


@pytest.fixture
async def admin_client(admin_app):
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed(db, *, billing_mode: str, cost: Decimal) -> LLMCall:
    row = LLMCall(
        user_id=f"u-{uuid.uuid4().hex[:12]}",
        feature="tutor",
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=cost,
        latency_ms=10,
        status=STATUS_OK,
        billing_mode=billing_mode,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_platform_total_excludes_byok(admin_client, auth_headers, db_session) -> None:
    admin = await auth_headers(role=Role.admin)
    # Platform rows cost real $; byok rows cost $0 to us (the user pays).
    await _seed(db_session, billing_mode="platform", cost=Decimal("0.010000"))
    await _seed(db_session, billing_mode="platform", cost=Decimal("0.020000"))
    # Even a non-zero byok cost row must be EXCLUDED from the platform total.
    await _seed(db_session, billing_mode="byok", cost=Decimal("0.500000"))

    r = await admin_client.get("/api/v1/admin/llm-calls/summary", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    # 0.01 + 0.02 = 0.03; the 0.5 byok row is excluded.
    assert Decimal(str(body["total_cost_usd"])) == Decimal("0.030000")
    assert body["total_calls"] == 3  # all rows still counted

    modes = {b["billing_mode"]: b for b in body["by_billing_mode"]}
    assert "byok" in modes and "platform" in modes
    assert modes["byok"]["calls"] == 1
    assert modes["platform"]["calls"] == 2


@pytest.mark.asyncio
async def test_list_view_exposes_billing_mode_no_key(
    admin_client, auth_headers, db_session
) -> None:
    admin = await auth_headers(role=Role.admin)
    await _seed(db_session, billing_mode="byok", cost=Decimal("0"))
    r = await admin_client.get("/api/v1/admin/llm-calls", headers=admin)
    assert r.status_code == 200
    rows = r.json()
    assert rows and rows[0]["billing_mode"] == "byok"
    flat = str(rows)
    assert "enc_blob" not in flat
    assert "api_key" not in flat
