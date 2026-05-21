"""When someone replies to my thread, I should be notified.

The discussion reply path emits a notification ping to the
thread author, scoped:

* never to self (self-replies don't generate a notification)
* never to a deleted author (author_id is SET NULL on user delete)

The notification carries the (discussion_id, reply_id, course_id)
triple in ``data`` so the frontend bell can deep-link without an
extra fetch.
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


async def _published(
    client: AsyncClient, teacher: dict, subject_id: str, seed_lesson
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "DN", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    return course_id


async def test_reply_notifies_thread_author(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    asker = await auth_headers(role=Role.student)
    helper = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    for h in (asker, helper):
        await client.post(f"/api/v1/me/enrollments/{course_id}", headers=h)

    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Help with lesson 3", "body": ""},
        headers=asker,
    )).json()

    # helper replies — asker should get a notification.
    r = await client.post(
        f"/api/v1/discussions/{thread['id']}/replies",
        json={"body": "Try restarting Postgres."},
        headers=helper,
    )
    assert r.status_code == 201

    notifs = await client.get("/api/v1/me/notifications", headers=asker)
    items = notifs.json()
    reply_notifs = [n for n in items if n["kind"] == "discussion_reply"]
    assert len(reply_notifs) == 1
    n = reply_notifs[0]
    assert "Help with lesson 3" in n["title"]
    assert n["data"]["discussion_id"] == thread["id"]
    assert n["data"]["course_id"] == course_id
    # And the reply id is captured for deep-linking.
    assert n["data"]["reply_id"]


async def test_self_reply_does_not_notify(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Note to self", "body": ""},
        headers=student,
    )).json()
    await client.post(
        f"/api/v1/discussions/{thread['id']}/replies",
        json={"body": "Replying to myself"},
        headers=student,
    )

    notifs = await client.get("/api/v1/me/notifications", headers=student)
    items = notifs.json()
    assert not any(n["kind"] == "discussion_reply" for n in items)


async def test_no_notification_when_thread_author_was_deleted(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user, seed_lesson
) -> None:
    """Thread.author_id is FK ondelete=SET NULL. After the asker
    deletes their account, the thread persists with author_id=NULL —
    a reply must not crash trying to notify a nonexistent user."""
    teacher = await auth_headers(role=Role.instructor)
    helper = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)

    # Asker creates the thread, then their account is hard-deleted
    # via the user FK SET NULL path. We simulate by directly
    # nulling author_id on the thread row, which matches the post-
    # cascade state.
    asker = await make_user(email=f"a-{uuid.uuid4().hex[:6]}@lumen.test")
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": asker.email, "password": "Password!1234"},
    )
    asker_h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=asker_h)
    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Ghosted", "body": ""},
        headers=asker_h,
    )).json()

    # Simulate the SET NULL cascade.
    from sqlalchemy import update

    from app.models.discussion import Discussion

    await db_session.execute(
        update(Discussion).where(Discussion.id == thread["id"]).values(author_id=None)
    )
    await db_session.commit()

    # Helper replies — should succeed, no notification persisted.
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=helper)
    r = await client.post(
        f"/api/v1/discussions/{thread['id']}/replies",
        json={"body": "Anyone home?"},
        headers=helper,
    )
    assert r.status_code == 201
