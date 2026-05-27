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


async def test_post_with_course_slug_resolves_to_course_id(
    client: AsyncClient,
    auth_headers,
    make_user,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """L32 — POST /tutor/turns with a known course_slug stores the
    resolved course_id on the turn row. The Celery task reads it back
    to scope the pgvector retrieval."""
    import uuid

    from app.models.course import Course, CourseStatus, Difficulty, Subject

    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    owner = await make_user(role=Role.instructor)
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"L32 {suffix}", slug=f"l32-{suffix}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"L32 Course {suffix}",
        slug=f"l32-course-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.commit()

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "Q?", "course_slug": course.slug},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    turn_id = r.json()["id"]

    row = await db_session.execute(select(TutorTurnJob).where(TutorTurnJob.id == turn_id))
    turn = row.scalar_one_or_none()
    assert turn is not None
    assert turn.course_id == course.id
    assert turn.user_message == "Q?"


async def test_post_with_unknown_course_slug_returns_404(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
) -> None:
    """L32 — unknown slug → 404, not 500. The streaming demo's caller
    (the frontend) won't normally hit this, but a typo in the URL bar
    on /learn/<slug> must surface as a clean error."""
    s = get_settings()
    monkeypatch.setattr(s, "feature_tutor_streaming", True)

    headers = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "Q?", "course_slug": "no-such-course-12345"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


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
