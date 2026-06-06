"""S2.6 — enroll gate routes through the central authorizer (can_enroll).

DB-backed (runs under ``make test.api``). Enrolling on a listed course works;
enrolling on a published-PRIVATE course is 403 ``enrollment.not_available`` for
a stranger but the owner can self-preview-enroll (FR-LEARN-01).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, ModerationState, Visibility
from app.models.user import Role


async def _subject(db: AsyncSession):
    from app.models.course import Subject

    s = Subject(title="Prog", slug=f"prog-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _course_with_lesson(client, headers, subject_id, title) -> str:
    cid = (
        await client.post(
            "/api/v1/courses",
            json={"title": title, "subject_id": subject_id, "overview": "x"},
            headers=headers,
        )
    ).json()["id"]
    m = (
        await client.post(f"/api/v1/courses/{cid}/modules", json={"title": "M"}, headers=headers)
    ).json()
    await client.post(
        f"/api/v1/courses/modules/{m['id']}/lessons",
        json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
        headers=headers,
    )
    return cid


async def _set_state(db, cid, *, visibility, status, moderation_state):
    await db.execute(
        update(Course)
        .where(Course.id == cid)
        .values(visibility=visibility, status=status, moderation_state=moderation_state)
    )
    await db.commit()


@pytest.mark.asyncio
async def test_enroll_listed_course_succeeds(client: AsyncClient, auth_headers, db_session) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id, "Listed")
    await _set_state(
        db_session,
        cid,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.approved,
    )
    student = await auth_headers(role=Role.student)
    r = await client.post(f"/api/v1/me/enrollments/{cid}", headers=student)
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_enroll_private_course_stranger_403(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id, "Private")
    await _set_state(
        db_session,
        cid,
        visibility=Visibility.private,
        status="published",
        moderation_state=ModerationState.none,
    )
    student = await auth_headers(role=Role.student)
    r = await client.post(f"/api/v1/me/enrollments/{cid}", headers=student)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "enrollment.not_available"


@pytest.mark.asyncio
async def test_owner_can_self_enroll_private(client: AsyncClient, auth_headers, db_session) -> None:
    """Owner self-preview-enroll on their own published-private course."""
    owner_headers = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, owner_headers, subject.id, "OwnerPrivate")
    await _set_state(
        db_session,
        cid,
        visibility=Visibility.private,
        status="published",
        moderation_state=ModerationState.none,
    )
    r = await client.post(f"/api/v1/me/enrollments/{cid}", headers=owner_headers)
    assert r.status_code == 201, r.text
