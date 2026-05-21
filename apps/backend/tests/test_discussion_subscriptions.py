"""Discussion subscriptions — opt-in follow with notification fanout.

Iter 90 extends iter 79's "notify thread author on reply" with a
proper subscribe/follow path:

* the thread author is auto-subscribed at create;
* a replier is auto-subscribed at reply (GitHub pattern: showing
  interest implies wanting followups);
* anyone else can subscribe via the new endpoint and unsubscribe
  the same way.

Reply notifications now fan out to *all* subscribers (capped at 200
to avoid runaway storms) except the replier themselves.
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
        json={"title": "Sub", "subject_id": subject_id, "overview": "x"},
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


async def test_author_auto_subscribed_and_is_subscribed_flag(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    asker = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=asker)

    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Q", "body": ""},
        headers=asker,
    )).json()

    detail = await client.get(f"/api/v1/discussions/{thread['id']}", headers=asker)
    assert detail.json()["is_subscribed"] is True


async def test_subscribe_endpoint_lets_non_author_follow(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    asker = await auth_headers(role=Role.student)
    watcher = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    for h in (asker, watcher):
        await client.post(f"/api/v1/me/enrollments/{course_id}", headers=h)
    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Popular", "body": ""},
        headers=asker,
    )).json()

    # watcher subscribes; flag flips.
    r = await client.post(
        f"/api/v1/discussions/{thread['id']}/subscribe", headers=watcher
    )
    assert r.status_code == 200
    detail = await client.get(
        f"/api/v1/discussions/{thread['id']}", headers=watcher
    )
    assert detail.json()["is_subscribed"] is True


async def test_subscribe_is_idempotent(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Double-subscribe must not 4xx (unique constraint would otherwise
    surface as a 500). _ensure_subscribed short-circuits if already in."""
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Idem", "body": ""},
        headers=student,
    )).json()
    for _ in range(3):
        r = await client.post(
            f"/api/v1/discussions/{thread['id']}/subscribe", headers=student
        )
        assert r.status_code == 200


async def test_unsubscribe_then_no_notification(
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
        json={"title": "Quiet", "body": ""},
        headers=asker,
    )).json()

    # Asker unsubscribes — they no longer want pings on this thread.
    rm = await client.delete(
        f"/api/v1/discussions/{thread['id']}/subscribe", headers=asker
    )
    assert rm.status_code == 200

    await client.post(
        f"/api/v1/discussions/{thread['id']}/replies",
        json={"body": "Anyone?"},
        headers=helper,
    )

    notifs = await client.get("/api/v1/me/notifications", headers=asker)
    assert not any(n["kind"] == "discussion_reply" for n in notifs.json())


async def test_replier_auto_subscribed(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    """Replying is an interest signal; the replier should get
    pinged on further replies without an explicit subscribe."""
    teacher = await auth_headers(role=Role.instructor)
    asker = await auth_headers(role=Role.student)
    first_helper = await auth_headers(role=Role.student)
    second_helper = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    for h in (asker, first_helper, second_helper):
        await client.post(f"/api/v1/me/enrollments/{course_id}", headers=h)
    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Wave", "body": ""},
        headers=asker,
    )).json()

    # First helper replies (auto-subscribes).
    await client.post(
        f"/api/v1/discussions/{thread['id']}/replies",
        json={"body": "Try X"},
        headers=first_helper,
    )
    # Second helper replies → both asker AND first_helper should see
    # a notification.
    await client.post(
        f"/api/v1/discussions/{thread['id']}/replies",
        json={"body": "Or maybe Y"},
        headers=second_helper,
    )

    asker_notifs = await client.get("/api/v1/me/notifications", headers=asker)
    first_notifs = await client.get("/api/v1/me/notifications", headers=first_helper)
    second_notifs = await client.get("/api/v1/me/notifications", headers=second_helper)

    assert any(n["kind"] == "discussion_reply" for n in asker_notifs.json())
    assert any(n["kind"] == "discussion_reply" for n in first_notifs.json())
    # The second helper just replied — they should NOT be notified
    # of their own action.
    assert not any(n["kind"] == "discussion_reply" for n in second_notifs.json())


async def test_anonymous_is_subscribed_false(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    thread = (await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Public", "body": ""},
        headers=student,
    )).json()

    # Anonymous read — is_subscribed must be False (and the endpoint
    # must succeed; subscription is per-user).
    r = await client.get(f"/api/v1/discussions/{thread['id']}")
    assert r.status_code == 200
    assert r.json()["is_subscribed"] is False
