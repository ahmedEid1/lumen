"""Course discussion threads — create, list, reply, delete, authz.

Forum-style alternative to the flat chat: threaded Q&A with title +
body, replies underneath, soft-delete for moderation, and the same
course-visibility rule the catalog uses.
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
    client: AsyncClient, teacher: dict, subject_id: str, seed_lesson, publish_and_list_course
) -> str:
    """Create + seed + publish + publicly list a course.

    S2 / ADR-0026 removed ``status`` from ``CourseUpdate`` (PATCH {status} now
    422s); lifecycle moved to ``POST /publish`` and publishing alone keeps the
    course PRIVATE. Discussions need the course publicly listed so students can
    enroll and the create gate (private-course block) is satisfied, so we use
    ``publish_and_list_course`` (publish + visibility=public + moderation=approved).
    """
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Disc", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await publish_and_list_course(course_id, teacher)
    return course_id


async def test_create_and_list_discussions(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson, publish_and_list_course)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    create = await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "How do quizzes work?", "body": "Got stuck on Q2"},
        headers=student,
    )
    assert create.status_code == 201, create.text
    thread_id = create.json()["id"]

    listed = await client.get(f"/api/v1/courses/{course_id}/discussions", headers=student)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == thread_id
    assert body["items"][0]["reply_count"] == 0


async def test_reply_bumps_thread_to_top(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    a = await auth_headers(role=Role.student)
    b = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson, publish_and_list_course)
    for h in (a, b):
        await client.post(f"/api/v1/me/enrollments/{course_id}", headers=h)

    # Two threads — A's then B's.
    a_thread = (
        await client.post(
            f"/api/v1/courses/{course_id}/discussions",
            json={"title": "First", "body": ""},
            headers=a,
        )
    ).json()
    b_thread = (
        await client.post(
            f"/api/v1/courses/{course_id}/discussions",
            json={"title": "Second", "body": ""},
            headers=b,
        )
    ).json()

    # B's reply to A's thread bumps A's to top.
    r = await client.post(
        f"/api/v1/discussions/{a_thread['id']}/replies",
        json={"body": "Same here"},
        headers=b,
    )
    assert r.status_code == 201

    listed = await client.get(f"/api/v1/courses/{course_id}/discussions", headers=a)
    items = listed.json()["items"]
    assert items[0]["id"] == a_thread["id"]
    assert items[0]["reply_count"] == 1
    assert items[1]["id"] == b_thread["id"]


async def test_get_thread_returns_replies_in_order(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson, publish_and_list_course)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    thread = (
        await client.post(
            f"/api/v1/courses/{course_id}/discussions",
            # schema requires title >= 3 chars; "T" 422'd.
            json={"title": "Thread", "body": ""},
            headers=student,
        )
    ).json()
    for body in ("first", "second", "third"):
        await client.post(
            f"/api/v1/discussions/{thread['id']}/replies",
            json={"body": body},
            headers=student,
        )

    r = await client.get(f"/api/v1/discussions/{thread['id']}", headers=student)
    bodies = [reply["body"] for reply in r.json()["replies"]]
    assert bodies == ["first", "second", "third"]


async def test_non_owner_cannot_delete_someone_elses_thread(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    author = await auth_headers(role=Role.student)
    stranger = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson, publish_and_list_course)
    for h in (author, stranger):
        await client.post(f"/api/v1/me/enrollments/{course_id}", headers=h)

    thread = (
        await client.post(
            f"/api/v1/courses/{course_id}/discussions",
            json={"title": "Mine", "body": ""},
            headers=author,
        )
    ).json()

    bad = await client.delete(f"/api/v1/discussions/{thread['id']}", headers=stranger)
    assert bad.status_code == 403
    assert bad.json()["error"]["code"] == "discussion.forbidden"

    # Author can delete their own.
    ok = await client.delete(f"/api/v1/discussions/{thread['id']}", headers=author)
    assert ok.status_code == 200

    # Soft-deleted threads disappear from the listing.
    listed = await client.get(f"/api/v1/courses/{course_id}/discussions", headers=author)
    assert listed.json()["total"] == 0


async def test_course_owner_can_moderate(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson, publish_and_list_course)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    thread = (
        await client.post(
            f"/api/v1/courses/{course_id}/discussions",
            json={"title": "Spam", "body": "..."},
            headers=student,
        )
    ).json()
    # Instructor (course owner) can delete a student's thread.
    r = await client.delete(f"/api/v1/discussions/{thread['id']}", headers=teacher)
    assert r.status_code == 200


async def test_drafts_dont_expose_threads_to_strangers(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Visibility rule: a stranger can't see threads on a draft course
    even if they know the course id.

    S2.9b (PR-25 / R-M1): a draft course is ``visibility=private``, so the
    *create* path is now blocked even for the owner (``discussion.course_private``)
    — the owner can no longer open a new thread while the course is private. We
    still need a thread to exist to prove the read-side existence-hiding, so we
    seed it directly via the DB (the canonical S2 pattern), then assert the
    stranger gets a 404 on the listing.
    """
    from sqlalchemy import select

    from app.models.course import Course
    from app.models.discussion import Discussion

    owner = await auth_headers(role=Role.instructor)
    stranger = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Draft", "subject_id": subject.id, "overview": "x"},
        headers=owner,
    )
    course_id = create.json()["id"]

    # A draft course is private — the owner's create attempt is now gated.
    blocked = await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Private chat", "body": ""},
        headers=owner,
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["code"] == "discussion.course_private"

    # Seed a thread directly so we can exercise the read-side existence-hiding.
    course = (await db_session.execute(select(Course).where(Course.id == course_id))).scalar_one()
    db_session.add(
        Discussion(course_id=course_id, author_id=course.owner_id, title="Private chat", body="")
    )
    await db_session.commit()

    # Stranger gets 404 (existence-hiding) on the listing.
    listed = await client.get(f"/api/v1/courses/{course_id}/discussions", headers=stranger)
    assert listed.status_code == 404


async def test_reply_endpoint_rate_limited(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published(client, teacher, subject.id, seed_lesson, publish_and_list_course)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    thread = (
        await client.post(
            f"/api/v1/courses/{course_id}/discussions",
            # schema requires title >= 3 chars.
            json={"title": "Thread", "body": ""},
            headers=student,
        )
    ).json()

    # 20/min — burst 22.
    last = None
    for i in range(22):
        last = await client.post(
            f"/api/v1/discussions/{thread['id']}/replies",
            json={"body": f"r{i}"},
            headers=student,
        )
    assert last is not None
    assert last.status_code == 429
