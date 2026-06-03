"""S2.5 — catalog/subject/search readers route through the central authorizer.

DB-backed (runs under ``make test.api``). A public+published+approved course
appears in /courses (catalog) + subject-tile counts; a published-private course
and a public+published+pending_review course do NOT; /courses/mine returns the
owner's private + pending + public courses.
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


async def _make_course_with_lesson(client, headers, subject_id, title) -> str:
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
async def test_catalog_lists_only_publicly_listed(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)

    listed = await _make_course_with_lesson(client, teacher, subject.id, "Listed")
    private = await _make_course_with_lesson(client, teacher, subject.id, "Private")
    pending = await _make_course_with_lesson(client, teacher, subject.id, "Pending")

    await _set_state(
        db_session,
        listed,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.approved,
    )
    await _set_state(
        db_session,
        private,
        visibility=Visibility.private,
        status="published",
        moderation_state=ModerationState.none,
    )
    await _set_state(
        db_session,
        pending,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.pending_review,
    )

    client.cookies.clear()
    body = (await client.get("/api/v1/courses")).json()
    ids = {item["id"] for item in body["items"]}
    assert listed in ids
    assert private not in ids
    assert pending not in ids


@pytest.mark.asyncio
async def test_subject_tile_counts_only_listed(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    listed = await _make_course_with_lesson(client, teacher, subject.id, "Listed")
    private = await _make_course_with_lesson(client, teacher, subject.id, "Private")
    await _set_state(
        db_session,
        listed,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.approved,
    )
    await _set_state(
        db_session,
        private,
        visibility=Visibility.private,
        status="published",
        moderation_state=ModerationState.none,
    )

    client.cookies.clear()
    subjects = (await client.get("/api/v1/subjects")).json()
    tile = next(s for s in subjects if s["slug"] == subject.slug)
    assert tile["total_courses"] == 1


@pytest.mark.asyncio
async def test_mine_returns_all_owner_states(client: AsyncClient, auth_headers, db_session) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    listed = await _make_course_with_lesson(client, teacher, subject.id, "Listed")
    private = await _make_course_with_lesson(client, teacher, subject.id, "Private")
    pending = await _make_course_with_lesson(client, teacher, subject.id, "Pending")
    await _set_state(
        db_session,
        listed,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.approved,
    )
    await _set_state(
        db_session,
        private,
        visibility=Visibility.private,
        status="draft",
        moderation_state=ModerationState.none,
    )
    await _set_state(
        db_session,
        pending,
        visibility=Visibility.public,
        status="published",
        moderation_state=ModerationState.pending_review,
    )

    mine = (await client.get("/api/v1/courses/mine", headers=teacher)).json()
    ids = {item["id"] for item in mine}
    assert {listed, private, pending} <= ids
