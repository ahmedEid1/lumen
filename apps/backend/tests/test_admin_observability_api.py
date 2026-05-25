"""Admin observability API — RBAC + drill-down + Celery health.

Lumen v2 Phase H7. The router is wave-2; the orchestrator mounts
it at ``/api/v1/admin`` after the wave returns. We attach it to
the test ``app`` fixture inline so the routes are reachable
without depending on the orchestrator step landing.

The Celery-health endpoint hits Redis via ``redis.asyncio`` and
the Celery control plane. Tests run against a real Redis
(``conftest.py``) but no worker is running in CI, so we exercise
the "no worker" branch implicitly — the endpoint returns 200 with
``active``/``scheduled`` as None and a ``note``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import admin_observability
from app.models.agent_trace import (  # noqa: F401 — register table for create_all
    TRACE_STATUS_OK,
    AgentTrace,
)
from app.models.llm_call import STATUS_OK, LLMCall
from app.models.retrieval_audit import RetrievalAudit  # noqa: F401 — register
from app.models.user import Role
from app.services.agent_tracer import record_step


# ---------- Fixtures ----------


@pytest_asyncio.fixture
async def admin_app(app):
    """Mount the observability router under the test app.

    The orchestrator will land the same include on master; this
    fixture is a shim so the API tests don't have to wait for it.
    Idempotent — repeated inclusion is fine (paths are unique).
    """
    paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
    if "/api/v1/admin/observability/celery" not in paths:
        app.include_router(
            admin_observability.router,
            prefix="/api/v1/admin",
            tags=["admin"],
        )
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


async def _seed_llm_call(
    db: AsyncSession,
    *,
    user_id: str,
    feature: str = "tutor.multi_agent",
) -> LLMCall:
    row = LLMCall(
        user_id=user_id,
        feature=feature,
        provider="anthropic",
        model="claude-sonnet-4-5",
        prompt_tokens=120,
        completion_tokens=60,
        cost_usd=Decimal("0.001200"),
        latency_ms=950,
        status=STATUS_OK,
        error_kind=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ---------- RBAC ----------


async def test_non_admin_blocked_from_trace_endpoint(
    admin_client: AsyncClient, auth_headers
) -> None:
    student = await auth_headers(role=Role.student)
    r = await admin_client.get(
        "/api/v1/admin/observability/llm-calls/anything/trace",
        headers=student,
    )
    assert r.status_code == 403


async def test_non_admin_blocked_from_retrieval_endpoint(
    admin_client: AsyncClient, auth_headers
) -> None:
    student = await auth_headers(role=Role.student)
    r = await admin_client.get(
        "/api/v1/admin/observability/retrieval", headers=student
    )
    assert r.status_code == 403


async def test_non_admin_blocked_from_celery_endpoint(
    admin_client: AsyncClient, auth_headers
) -> None:
    student = await auth_headers(role=Role.student)
    r = await admin_client.get(
        "/api/v1/admin/observability/celery", headers=student
    )
    assert r.status_code == 403


async def test_instructor_blocked_same_as_student(
    admin_client: AsyncClient, auth_headers
) -> None:
    """An instructor is not an admin — 403 across all three endpoints."""
    instructor = await auth_headers(role=Role.instructor)
    for path in [
        "/api/v1/admin/observability/llm-calls/x/trace",
        "/api/v1/admin/observability/retrieval",
        "/api/v1/admin/observability/celery",
    ]:
        r = await admin_client.get(path, headers=instructor)
        assert r.status_code == 403, f"{path}: {r.status_code}"


# ---------- Trace drill-down ----------


async def test_admin_can_fetch_trace_for_existing_call(
    admin_client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
) -> None:
    """Seed an LLM call + a few traces → admin gets a nested response."""
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    call = await _seed_llm_call(db_session, user_id=user_id)
    plan = await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="plan",
        step_index=0,
        parent_call_id=call.id,
        payload={"goal": "answer the user"},
    )
    assert plan is not None
    await record_step(
        db_session,
        user_id=user_id,
        feature="tutor.multi_agent",
        step="sub_agent.retriever",
        step_index=1,
        parent_call_id=call.id,
        parent_trace_id=plan.id,
        payload={"query": "what is X"},
    )
    await db_session.commit()

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        f"/api/v1/admin/observability/llm-calls/{call.id}/trace",
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["call"]["call_id"] == call.id
    assert body["call"]["feature"] == "tutor.multi_agent"
    assert body["call"]["model"] == "claude-sonnet-4-5"
    assert len(body["traces"]) == 2
    steps = [t["step"] for t in body["traces"]]
    assert "plan" in steps
    assert "sub_agent.retriever" in steps
    # ``audits`` is present in the payload (possibly empty).
    assert "audits" in body
    assert isinstance(body["audits"], list)


async def test_missing_call_id_returns_404(
    admin_client: AsyncClient, auth_headers
) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        "/api/v1/admin/observability/llm-calls/does-not-exist/trace",
        headers=admin,
    )
    assert r.status_code == 404
    body = r.json()
    # Error envelope from ``app.core.errors`` — ``{"error": {...}}``.
    assert body["error"]["code"] == "observability.call_not_found"


async def test_trace_endpoint_returns_empty_lists_when_no_traces_recorded(
    admin_client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
) -> None:
    """An LLM call with no traces still gets a clean response."""
    user_id = f"u-{uuid.uuid4().hex[:16]}"
    call = await _seed_llm_call(db_session, user_id=user_id, feature="tutor")

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        f"/api/v1/admin/observability/llm-calls/{call.id}/trace",
        headers=admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["call"]["call_id"] == call.id
    assert body["traces"] == []
    assert body["audits"] == []


# ---------- Retrieval audits list ----------


async def test_admin_can_list_retrieval_audits(
    admin_client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
) -> None:
    """Seed two audits → list returns them, newest first."""
    user_a = f"u-{uuid.uuid4().hex[:16]}"
    user_b = f"u-{uuid.uuid4().hex[:16]}"

    db_session.add(
        RetrievalAudit(
            user_id=user_a,
            feature="tutor",
            query="alpha",
            course_id="crs_x",
            chunks=[{"chunk_id": "c1", "lesson_id": "l1", "score": 0.1, "snippet": "alpha"}],
            top_score=0.1,
        )
    )
    db_session.add(
        RetrievalAudit(
            user_id=user_b,
            feature="learning_path",
            query="beta",
            course_id=None,
            chunks=[],
            top_score=None,
        )
    )
    await db_session.commit()

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        "/api/v1/admin/observability/retrieval", headers=admin
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    # The test DB isn't truncated of retrieval_audits between every
    # test, so we filter to the two we seeded here.
    seen = {row["query"] for row in rows}
    assert "alpha" in seen
    assert "beta" in seen


async def test_retrieval_list_filters_by_user_id(
    admin_client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
) -> None:
    user_a = f"u-{uuid.uuid4().hex[:16]}"
    user_b = f"u-{uuid.uuid4().hex[:16]}"
    db_session.add(
        RetrievalAudit(
            user_id=user_a,
            feature="tutor",
            query="filter-target",
            course_id=None,
            chunks=[],
            top_score=None,
        )
    )
    db_session.add(
        RetrievalAudit(
            user_id=user_b,
            feature="tutor",
            query="other-user",
            course_id=None,
            chunks=[],
            top_score=None,
        )
    )
    await db_session.commit()

    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        f"/api/v1/admin/observability/retrieval?user_id={user_a}",
        headers=admin,
    )
    assert r.status_code == 200
    rows = r.json()
    assert rows  # at least one
    assert all(row["user_id"] == user_a for row in rows)


# ---------- Celery health ----------


async def test_admin_can_fetch_celery_health(
    admin_client: AsyncClient, auth_headers
) -> None:
    """The endpoint returns 200 even when no worker is running.

    The test env has Redis up but no worker, so ``inspect.ping()``
    returns None and the response carries a ``note`` to that effect.
    Queue depths come back from a direct ``LLEN`` and are typically
    zero in a clean test DB.
    """
    admin = await auth_headers(role=Role.admin)
    r = await admin_client.get(
        "/api/v1/admin/observability/celery", headers=admin
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Redis itself is healthy in the test env.
    assert body["redis_status"] == "ok"
    # We surface at least the default ``celery`` queue.
    names = {q["name"] for q in body["queues"]}
    assert "celery" in names
    # Without a worker, active+scheduled are either None (no worker
    # reachable) or empty dicts (a fluke where a worker happens to
    # respond). Both are acceptable; we just confirm the shape.
    assert "active" in body
    assert "scheduled" in body
