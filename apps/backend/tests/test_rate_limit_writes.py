"""Rate limits on the heavier write endpoints.

Pre-iter-53 only the auth endpoints carried explicit rate limits.
Two real DOS surfaces were left wide open for an authenticated user:

* ``/me/progress/lessons/{id}/quiz`` — grading walks the full question
  list and writes ``LessonProgress`` rows / can issue certificates.
  A 50-question quiz replayed in a tight loop burns CPU + DB writes.

* ``/chat/courses/{id}/messages`` — every POST inserts a row, fans
  out via Redis pub/sub, and broadcasts to every WS subscriber. An
  enrolled bad actor could trivially flood a course's chat.

Iter 53 adds 20/minute on quiz submit and 30/minute on chat POST.
The autouse limiter-reset fixture in conftest ensures these tests
start with fresh buckets.
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


async def _published_course_with_lesson(
    client: AsyncClient, teacher: dict, subject_id: str
) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "RL", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules",
            json={"title": "M"},
            headers=teacher,
        )
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Quiz",
                "type": "quiz",
                "data": {
                    "type": "quiz",
                    "pass_score": 50,
                    "questions": [
                        {
                            "id": "q1",
                            "prompt": "Pick A",
                            "kind": "single",
                            "choices": [
                                {"id": "a", "text": "A"},
                                {"id": "b", "text": "B"},
                            ],
                            "answer_keys": ["a"],
                        }
                    ],
                },
            },
            headers=teacher,
        )
    ).json()
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    return course_id, lesson["id"]


async def test_quiz_submit_rate_limited(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _published_course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    # 20/minute — burst 22 to drain the bucket.
    last = None
    for _ in range(22):
        last = await client.post(
            f"/api/v1/me/progress/lessons/{lesson_id}/quiz",
            json={"answers": {"q1": ["a"]}},
            headers=student,
        )
    assert last is not None
    assert last.status_code == 429, last.text
    assert last.json()["error"]["code"] == "rate_limited"


async def test_chat_post_rate_limited(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Chatty", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    # 30/minute — burst 32. Each POST publishes to Redis but with no
    # WS subscriber that's a fast no-op; we're verifying the *gate*,
    # not chat correctness.
    last = None
    for i in range(32):
        last = await client.post(
            f"/api/v1/chat/courses/{course_id}/messages",
            json={"body": f"flood {i}"},
            headers=student,
        )
    assert last is not None
    assert last.status_code == 429, last.text
    assert last.json()["error"]["code"] == "rate_limited"


async def test_quiz_limit_isolated_per_test(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """The autouse limiter-reset fixture must clear the bucket between
    tests; otherwise rate-limit regressions become flaky."""
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _published_course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    r = await client.post(
        f"/api/v1/me/progress/lessons/{lesson_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student,
    )
    assert r.status_code != 429
