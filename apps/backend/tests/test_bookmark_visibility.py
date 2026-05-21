"""Regression: bookmarks must not expose courses the viewer can't see.

Before iteration 47 ``add_bookmark`` only checked
``courses_repo.get_course`` (filters ``deleted_at`` but not status), so
a user who knew (or guessed) the id of another instructor's *draft*
course could:

* POST ``/api/v1/me/bookmarks/{id}`` → 201;
* GET ``/api/v1/me/bookmarks`` → the bookmark listing renders the
  course as ``CourseListItem``, leaking title, overview, owner,
  cover, subject, tags, and stats — every field the catalog hides
  from non-owners.

This is the same shape as the duplicate-course leak fixed in iter 46.
We now run ``can_view_course`` at both bookmark-add time and list
time, so a bookmark can never surface a course the viewer wouldn't
see on the detail page or in the catalog. Existing bookmarks pointing
at a course that has since gone draft are silently filtered from the
listing rather than ghost-leaking when the course visibility flips.
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


async def _create_draft(
    client: AsyncClient, headers: dict, subject_id: str, title: str = "Private"
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    assert create.status_code == 201
    return create.json()["id"]


async def test_cannot_bookmark_other_users_draft(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    owner = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _create_draft(client, owner, subject.id)

    r = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    # 404 (not 403) — match the existence-hiding posture used elsewhere.
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "course.not_found"

    # Sanity: nothing in the listing.
    listed = await client.get("/api/v1/me/bookmarks", headers=student)
    assert listed.status_code == 200
    assert all(c["id"] != course_id for c in listed.json())


async def test_cannot_bookmark_other_users_archived(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    owner = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _create_draft(client, owner, subject.id, "Retired")
    await seed_lesson(course_id, owner)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=owner
    )
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=owner
    )

    r = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "course.not_found"


async def test_existing_bookmark_hidden_when_course_unpublished(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Bookmark while published, then owner moves it back to draft —
    the listing must not keep rendering the now-private course."""
    owner = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _create_draft(client, owner, subject.id, "Was public")
    await seed_lesson(course_id, owner)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=owner
    )

    # Bookmark while published — works.
    added = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    assert added.status_code == 201
    pre = await client.get("/api/v1/me/bookmarks", headers=student)
    assert any(c["id"] == course_id for c in pre.json())

    # Owner pulls it back to draft.
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "draft"}, headers=owner
    )

    post = await client.get("/api/v1/me/bookmarks", headers=student)
    assert post.status_code == 200
    assert all(c["id"] != course_id for c in post.json())


async def test_owner_can_bookmark_their_own_draft(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """The visibility predicate already grants owners access to their own
    drafts — bookmark should follow."""
    owner = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id = await _create_draft(client, owner, subject.id, "Mine")

    r = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=owner)
    assert r.status_code == 201
    listed = await client.get("/api/v1/me/bookmarks", headers=owner)
    assert any(c["id"] == course_id for c in listed.json())


async def test_enrolled_learner_can_bookmark_archived_course(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Iter 24 lets enrolled learners keep reading archived courses —
    bookmark should follow the same posture."""
    owner = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _create_draft(client, owner, subject.id, "Persists")
    await seed_lesson(course_id, owner)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=owner
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "archived"}, headers=owner
    )

    r = await client.put(f"/api/v1/me/bookmarks/{course_id}", headers=student)
    assert r.status_code == 201, r.text
    listed = await client.get("/api/v1/me/bookmarks", headers=student)
    assert any(c["id"] == course_id for c in listed.json())
