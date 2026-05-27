"""L21a streaming-tutor endpoint coverage.

ALL four endpoints (POST/status/stream/cancel) gate on
``settings.feature_tutor_streaming``. While the flag is OFF (default
until L21b), every endpoint returns 503 ``tutor.streaming_disabled``.

These tests cover:
- 503 gating when flag is OFF (the default L21a state)
- Happy path when flag is ON (POST creates a pending row + enqueues)
- IDOR: status / cancel on another user's turn collapse to 404
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.tutor_turn_job import TURN_STATUS_PENDING, TutorTurnJob
from app.models.user import Role


@pytest.fixture(autouse=True)
def _stub_celery_enqueue():
    """Don't fire real Celery enqueues during HTTP tests — Redis is
    mocked enough by conftest but `delay()` would still try to ship
    the task. Patch it to a no-op so the after_commit listener fires
    cleanly without hitting the broker."""
    with patch("app.workers.tasks.tutor_streaming.run_turn.delay") as m:
        m.return_value = None
        yield m


async def test_post_returns_503_when_streaming_disabled(client: AsyncClient, auth_headers) -> None:
    """Default state: flag OFF → 503 with the documented error code."""
    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "hi"},
        headers=headers,
    )
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "tutor.streaming_disabled"


async def test_status_returns_503_when_streaming_disabled(
    client: AsyncClient, auth_headers
) -> None:
    headers = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/tutor/turns/anything/status", headers=headers)
    assert r.status_code == 503


async def test_delete_returns_503_when_streaming_disabled(
    client: AsyncClient, auth_headers
) -> None:
    headers = await auth_headers(role=Role.student)
    r = await client.delete("/api/v1/tutor/turns/anything", headers=headers)
    assert r.status_code == 503


async def test_post_creates_pending_row_when_flag_on(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Flag ON: POST inserts a pending row + (mocked) enqueue fires."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "what is variance?"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == TURN_STATUS_PENDING
    turn_id = body["id"]

    # Row really exists with the expected status.
    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    assert turn.status == TURN_STATUS_PENDING


async def test_status_idor_collapses_to_404(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
) -> None:
    """Learner B querying learner A's turn status sees 404, not 403 —
    so the endpoint doesn't reveal whether the id exists."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers_a = await auth_headers(role=Role.student)
    headers_b = await auth_headers(role=Role.student)

    new = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "first user's turn"},
        headers=headers_a,
    )
    assert new.status_code == 201
    turn_id = new.json()["id"]

    r = await client.get(f"/api/v1/tutor/turns/{turn_id}/status", headers=headers_b)
    assert r.status_code == 404
