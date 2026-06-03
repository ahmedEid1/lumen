"""S2.6 — the streaming-tutor slug->id lookup gates on can_view_course.

DB-backed (runs under ``make test.api``). A non-owner cannot resolve a
published-PRIVATE course (404 existence-hide), but the OWNER can (self-learn,
FR-LEARN-01). Listed courses resolve for anyone.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.user import Role


@pytest.fixture(autouse=True)
def _stub_celery_enqueue():
    with patch("app.workers.tasks.tutor_streaming.run_turn.delay") as m:
        m.return_value = None
        yield m


@pytest.fixture(autouse=True)
def _stub_cost_scripts():
    from unittest.mock import AsyncMock

    with (
        patch("app.core.cost_scripts.check_concurrency", new=AsyncMock(return_value=(True, 0))),
        patch("app.core.cost_scripts.reserve_cost", new=AsyncMock(return_value=(True, 0.0, 0.0))),
        patch("app.core.cost_scripts.reconcile_cost", new=AsyncMock(return_value=None)),
        patch("app.core.cost_scripts.release_concurrency", new=AsyncMock(return_value=None)),
    ):
        yield


async def _mk_course(db, owner, *, visibility, status, moderation_state):
    from app.models.course import Course, Difficulty, Subject

    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=f"C {suffix}",
        slug=f"c-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=status,
        visibility=visibility,
        moderation_state=moderation_state,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


@pytest.mark.asyncio
async def test_streaming_private_course_404_for_stranger(
    client: AsyncClient, auth_headers, make_user, db_session: AsyncSession, monkeypatch
) -> None:
    from app.models.course import CourseStatus, ModerationState, Visibility

    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner = await make_user(role=Role.instructor)
    course = await _mk_course(
        db_session,
        owner,
        visibility=Visibility.private,
        status=CourseStatus.published,
        moderation_state=ModerationState.none,
    )
    stranger = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "Q?", "course_slug": course.slug},
        headers=stranger,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_streaming_private_course_owner_self_learn(
    client: AsyncClient, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """The owner can stream-tutor their own published-private course."""
    from app.models.course import (
        Course,
        CourseStatus,
        Difficulty,
        ModerationState,
        Subject,
        Visibility,
    )

    monkeypatch.setattr(get_settings(), "feature_tutor_streaming", True)
    owner_headers = await auth_headers(role=Role.instructor)
    # Resolve the owner user id via /me so we create the course under them.
    me = (await client.get("/api/v1/users/me", headers=owner_headers)).json()
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db_session.add(subject)
    await db_session.flush()
    course = Course(
        owner_id=me["id"],
        subject_id=subject.id,
        title=f"C {suffix}",
        slug=f"c-{suffix}",
        overview="o",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        visibility=Visibility.private,
        moderation_state=ModerationState.none,
    )
    db_session.add(course)
    await db_session.commit()

    r = await client.post(
        "/api/v1/tutor/turns",
        json={"content": "Q?", "course_slug": course.slug},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
