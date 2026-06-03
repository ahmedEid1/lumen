"""S2.9b (PR-25 / R-M1) — discussion CREATE is gated on course visibility.

DB-backed (runs under ``make test.api``). Creating a discussion on a
``visibility=private`` course is rejected (403 ``discussion.course_private``),
distinct from the read authorizer; on a publicly-listed course the owner can
create one. Reads of existing discussions stay owner+enrolled (unchanged) — the
gate is create-only.
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


async def _course(client, headers, subject_id) -> str:
    cid = (
        await client.post(
            "/api/v1/courses",
            json={"title": "D", "subject_id": subject_id, "overview": "x"},
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
async def test_create_discussion_blocked_on_private_course(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course(client, teacher, subject.id)
    await _set_state(
        db_session,
        cid,
        visibility=Visibility.private,
        status="published",
        moderation_state=ModerationState.none,
    )
    # Even the owner cannot start a new discussion while private.
    # (title >= 3 chars; "Q" alone 422s on schema validation before the gate.)
    r = await client.post(
        f"/api/v1/courses/{cid}/discussions",
        json={"title": "Question", "body": "body"},
        headers=teacher,
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "discussion.course_private"


@pytest.mark.asyncio
async def test_create_discussion_allowed_on_listed_course(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course(client, teacher, subject.id)
    await _set_state(
        db_session,
        cid,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.approved,
    )
    r = await client.post(
        f"/api/v1/courses/{cid}/discussions",
        json={"title": "Question", "body": "body"},
        headers=teacher,
    )
    assert r.status_code in (200, 201), r.text
