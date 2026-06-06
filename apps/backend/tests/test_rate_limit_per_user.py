"""Per-user rate-limit keying.

Earlier, slowapi's default key was the remote address. Two
learners behind the same NAT (office, school, coffee shop) shared
one bucket — a single noisy account could lock out every colleague
on the same gateway. The current ``_identity_key`` derives the
bucket from the JWT ``sub`` when present, the auth cookie when
not, and only falls back to IP for fully anonymous traffic.

We assert this by exhausting the discussion-reply bucket
(20/minute) as one user and verifying a second user — same test
client, same "IP" from slowapi's perspective — can still post.
Discussion replies took over from the per-course WebSocket chat
endpoint (removed in rebuild Cut A8); they're the closest
remaining authenticated write that fires per-user and is easy to
seed in a test.
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


async def _published_course(
    client: AsyncClient, teacher: dict, subject_id: str, seed_lesson, publish_and_list_course
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Shared", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await publish_and_list_course(course_id, teacher)
    return course_id


async def test_two_users_share_ip_but_not_bucket(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    seed_lesson,
    publish_and_list_course,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    noisy = await auth_headers(role=Role.student)
    quiet = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id = await _published_course(
        client, teacher, subject.id, seed_lesson, publish_and_list_course
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=noisy)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=quiet)

    # Open a thread the rate-limited replies will hang off of. The
    # teacher posts the discussion (the create endpoint is 10/minute,
    # but we only call it once) so it doesn't contend with the
    # 20/minute reply bucket we're testing.
    thread = await client.post(
        f"/api/v1/courses/{course_id}/discussions",
        json={"title": "Anyone awake?", "body": "ping"},
        headers=teacher,
    )
    assert thread.status_code == 201, thread.text
    thread_id = thread.json()["id"]

    # Drain noisy's reply bucket (20/minute). Each POST is a real DB
    # write but with no notification fanout because the teacher is
    # the thread author and we ignore self-notifications anyway.
    noisy_last = None
    for i in range(22):
        noisy_last = await client.post(
            f"/api/v1/discussions/{thread_id}/replies",
            json={"body": f"noisy {i}"},
            headers=noisy,
        )
    assert noisy_last is not None
    assert noisy_last.status_code == 429

    # quiet shares the same IP but a different identity → fresh bucket.
    quiet_r = await client.post(
        f"/api/v1/discussions/{thread_id}/replies",
        json={"body": "first time"},
        headers=quiet,
    )
    assert quiet_r.status_code == 201, quiet_r.text


async def test_anonymous_still_keys_by_ip(client: AsyncClient) -> None:
    """Sanity: anonymous flow falls back to IP. We can't easily simulate
    two distinct anonymous clients in one process, so we just verify
    that an unauthed request still drains the bucket and 429s, proving
    the fallback is wired."""
    last = None
    # /auth/login is 10/minute. Anonymous → keyed by IP.
    for _ in range(12):
        last = await client.post(
            "/api/v1/auth/login",
            json={"email": "anyone@lumen.test", "password": "wrong"},
        )
    assert last is not None
    assert last.status_code == 429
