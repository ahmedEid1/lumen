"""Admin LLM-cost API — list + summary + RBAC.

The router is wave-1; the orchestrator mounts it at
``/api/v1/admin/llm-calls`` after this PR lands. To exercise the
endpoints here without depending on the orchestrator step, we mount
the router onto a copy of the app fixture under that prefix.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import admin_llm_calls
from app.models.llm_call import (
    STATUS_BUDGET_EXCEEDED,
    STATUS_ERROR,
    STATUS_OK,
    LLMCall,
)
from app.models.user import Role

# ---------- Fixtures ----------


@pytest_asyncio.fixture
async def admin_app(app):
    """Mount the (currently-unregistered) admin LLM router for the test.

    The router is owned by H1 but the orchestrator registers it after
    wave-1 returns. We attach it directly here so the test doesn't
    depend on that step landing.
    """
    app.include_router(admin_llm_calls.router, prefix="/api/v1/admin", tags=["admin"])
    return app


@pytest_asyncio.fixture
async def admin_client(admin_app):
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as c:
        yield c


async def _seed_call(
    db: AsyncSession,
    *,
    user_id: str,
    feature: str = "tutor",
    status: str = STATUS_OK,
    cost: Decimal = Decimal("0.001000"),
    model: str = "llama-3.3-70b-versatile",
    when: datetime | None = None,
) -> LLMCall:
    row = LLMCall(
        user_id=user_id,
        feature=feature,
        provider="openai",
        model=model,
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=cost,
        latency_ms=120,
        status=status,
        error_kind="RuntimeError" if status == STATUS_ERROR else None,
    )
    if when is not None:
        row.created_at = when
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ---------- RBAC ----------


async def test_non_admin_forbidden_from_list(admin_client: AsyncClient, auth_headers) -> None:
    student = await auth_headers(role=Role.student)
    r = await admin_client.get("/api/v1/admin/llm-calls", headers=student)
    assert r.status_code == 403


async def test_non_admin_forbidden_from_summary(admin_client: AsyncClient, auth_headers) -> None:
    student = await auth_headers(role=Role.student)
    r = await admin_client.get("/api/v1/admin/llm-calls/summary", headers=student)
    assert r.status_code == 403


async def test_instructor_forbidden_from_list(admin_client: AsyncClient, auth_headers) -> None:
    """Instructor is not admin — must 403 same as student."""
    instructor = await auth_headers(role=Role.instructor)
    r = await admin_client.get("/api/v1/admin/llm-calls", headers=instructor)
    assert r.status_code == 403


# ---------- List endpoint ----------


async def test_admin_can_list_calls(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    await _seed_call(db_session, user_id=user_id, feature="tutor")
    await _seed_call(db_session, user_id=user_id, feature="authoring.outline")

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get("/api/v1/admin/llm-calls", headers=admin)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 2
    seen_features = {row["feature"] for row in rows if row["user_id"] == user_id}
    assert seen_features == {"tutor", "authoring.outline"}


async def test_list_filters_by_user_id(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    user_a = f"u-{uuid.uuid4().hex[:16]}"
    user_b = f"u-{uuid.uuid4().hex[:16]}"
    await _seed_call(db_session, user_id=user_a, feature="tutor")
    await _seed_call(db_session, user_id=user_b, feature="tutor")

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(f"/api/v1/admin/llm-calls?user_id={user_a}", headers=admin)
    assert r.status_code == 200
    rows = r.json()
    assert all(row["user_id"] == user_a for row in rows)
    assert any(row["user_id"] == user_a for row in rows)


async def test_list_filters_by_feature(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    await _seed_call(db_session, user_id=user_id, feature="tutor")
    await _seed_call(db_session, user_id=user_id, feature="eval.judge")

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get("/api/v1/admin/llm-calls?feature=eval.judge", headers=admin)
    assert r.status_code == 200
    rows = r.json()
    assert all(row["feature"] == "eval.judge" for row in rows)


async def test_list_filters_by_status(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    await _seed_call(db_session, user_id=user_id, status=STATUS_OK)
    await _seed_call(db_session, user_id=user_id, status=STATUS_ERROR)
    await _seed_call(db_session, user_id=user_id, status=STATUS_BUDGET_EXCEEDED, cost=Decimal("0"))

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        f"/api/v1/admin/llm-calls?status=error&user_id={user_id}",
        headers=admin,
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert all(row["status"] == "error" for row in rows)


# ---------- Summary endpoint ----------


async def test_summary_aggregates_total_and_by_feature(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Seed two features → summary shows them both with correct totals."""
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    await _seed_call(db_session, user_id=user_id, feature="tutor", cost=Decimal("0.010000"))
    await _seed_call(db_session, user_id=user_id, feature="tutor", cost=Decimal("0.020000"))
    await _seed_call(
        db_session,
        user_id=user_id,
        feature="authoring.outline",
        cost=Decimal("0.050000"),
    )

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get("/api/v1/admin/llm-calls/summary", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_calls"] >= 3
    # 0.01 + 0.02 + 0.05 = 0.08 minimum
    assert Decimal(str(body["total_cost_usd"])) >= Decimal("0.080000")

    by_feature = {b["feature"]: b for b in body["by_feature"]}
    assert "tutor" in by_feature
    assert "authoring.outline" in by_feature
    # The tutor bucket must include at least our two seeded rows + 0.030
    assert Decimal(str(by_feature["tutor"]["cost_usd"])) >= Decimal("0.030000")


async def test_summary_includes_by_day_buckets(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """``by_day`` returns one bucket per UTC day with data in the window."""
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    today = datetime.now(UTC)
    yesterday = today - timedelta(days=1)
    await _seed_call(db_session, user_id=user_id, cost=Decimal("0.001000"), when=today)
    await _seed_call(db_session, user_id=user_id, cost=Decimal("0.002000"), when=yesterday)

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get("/api/v1/admin/llm-calls/summary?days=7", headers=admin)
    assert r.status_code == 200
    by_day = r.json()["by_day"]
    days_returned = {b["day"] for b in by_day}
    assert today.date().isoformat() in days_returned
    assert yesterday.date().isoformat() in days_returned


async def test_summary_window_excludes_old_data(
    admin_client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """A row from 30 days ago must not appear in a 7-day rollup."""
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    old = datetime.now(UTC) - timedelta(days=30)
    await _seed_call(
        db_session,
        user_id=user_id,
        cost=Decimal("999.000000"),
        when=old,
        feature="ancient.feature",
    )

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get("/api/v1/admin/llm-calls/summary?days=7", headers=admin)
    assert r.status_code == 200
    body = r.json()
    by_feature_names = {b["feature"] for b in body["by_feature"]}
    assert "ancient.feature" not in by_feature_names
