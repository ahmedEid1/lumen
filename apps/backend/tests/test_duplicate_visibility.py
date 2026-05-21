"""Regression: duplicate_course must not leak drafts owned by others.

Before iteration 46 ``POST /api/v1/courses/{id}/duplicate`` loaded
the source via ``courses_repo.get_course`` (which only filters
``deleted_at IS NULL``) and cloned it. The docstring already said
*"instructors can copy any **published** course to remix it"* — but
the code didn't enforce that. So an instructor who knew (or guessed)
the course id of another instructor's *unpublished* draft could
duplicate it into their own account and end up with every module
and lesson the author hadn't yet released.

Catalog / detail / search all rightly hide non-published courses
from non-owners. Duplicate now matches: only published sources are
duplicable by an arbitrary instructor; drafts and archived sources
are duplicable only by the owner or an admin. Non-owner attempts
return 404 (not 403) so we don't even confirm the course exists to
a caller who shouldn't see it.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _create_course(
    client: AsyncClient, headers: dict, subject_id: str, title: str = "Private"
) -> str:
    """Create a course but don't publish it — it stays draft."""
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    assert create.status_code == 201
    return create.json()["id"]


async def test_cannot_duplicate_other_instructors_draft(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    owner = await auth_headers(role=Role.instructor)
    other = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, owner, subject.id)

    r = await client.post(f"/api/v1/courses/{course_id}/duplicate", headers=other)
    # 404 (not 403) — don't confirm existence to a stranger.
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "course.not_found"


async def test_cannot_duplicate_other_instructors_archived(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    owner = await auth_headers(role=Role.instructor)
    other = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, owner, subject.id, title="Retired")
    await seed_lesson(course_id, owner)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=owner
    )
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=owner
    )

    r = await client.post(f"/api/v1/courses/{course_id}/duplicate", headers=other)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "course.not_found"


async def test_owner_can_duplicate_their_own_draft(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    owner = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, owner, subject.id, title="Mine")

    r = await client.post(f"/api/v1/courses/{course_id}/duplicate", headers=owner)
    assert r.status_code == 201, r.text
    assert r.json()["title"] == "Mine (copy)"
    assert r.json()["status"] == "draft"


async def test_admin_can_duplicate_anyone_draft(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    owner = await auth_headers(role=Role.instructor)
    admin = await auth_headers(role=Role.admin)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, owner, subject.id, title="Private")

    r = await client.post(f"/api/v1/courses/{course_id}/duplicate", headers=admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["title"] == "Private (copy)"


async def test_any_instructor_can_duplicate_a_published_source(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """The existing happy path — locked down here too as a guard against
    accidental over-tightening of the visibility rule."""
    owner = await auth_headers(role=Role.instructor)
    other = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_course(client, owner, subject.id, title="Public")
    await seed_lesson(course_id, owner)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=owner
    )

    r = await client.post(f"/api/v1/courses/{course_id}/duplicate", headers=other)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"
