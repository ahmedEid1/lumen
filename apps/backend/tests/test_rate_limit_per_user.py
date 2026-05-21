"""Per-user rate-limit keying.

Pre-iter 61 slowapi's default key was the remote address. Two
learners behind the same NAT (office, school, coffee shop) shared
one bucket — a single noisy account could lock out every colleague
on the same gateway. The new ``_identity_key`` derives the bucket
from the JWT ``sub`` when present, the auth cookie when not, and
only falls back to IP for fully anonymous traffic.

We assert this by exhausting the chat-post bucket (30/minute, iter
53) as one user and verifying a second user — same test client,
same "IP" from slowapi's perspective — can still post.
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


async def test_two_users_share_ip_but_not_bucket(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    noisy = await auth_headers(role=Role.student)
    quiet = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Shared", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=noisy)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=quiet)

    # Drain noisy's bucket (30/minute, iter 53).
    noisy_last = None
    for i in range(32):
        noisy_last = await client.post(
            f"/api/v1/chat/courses/{course_id}/messages",
            json={"body": f"noisy {i}"},
            headers=noisy,
        )
    assert noisy_last is not None
    assert noisy_last.status_code == 429

    # quiet shares the same IP but a different identity → fresh bucket.
    quiet_r = await client.post(
        f"/api/v1/chat/courses/{course_id}/messages",
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
    # /auth/login is 10/minute (iter 39-ish). Anonymous → keyed by IP.
    for _ in range(12):
        last = await client.post(
            "/api/v1/auth/login",
            json={"email": "anyone@lumen.test", "password": "wrong"},
        )
    assert last is not None
    assert last.status_code == 429
