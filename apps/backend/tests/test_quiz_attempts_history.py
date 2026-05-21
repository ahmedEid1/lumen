"""Append-only quiz attempt history.

Pre-iter 73 only ``LessonProgress.payload`` held the latest attempt;
retakes silently overwrote it. The new ``quiz_attempts`` table is
append-only — every submission writes a fresh row, indexed for
"latest N attempts for this (enrollment, lesson)" reads.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.quiz_attempt import QuizAttempt
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _quiz_lesson(
    client: AsyncClient, teacher: dict, subject_id: str
) -> tuple[str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Q", "subject_id": subject_id, "overview": "x"},
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


async def test_each_submission_records_a_new_attempt_row(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _quiz_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    # Three submissions: fail, fail, pass — every one persists.
    for answers in (["b"], ["b"], ["a"]):
        r = await client.post(
            f"/api/v1/me/progress/lessons/{lesson_id}/quiz",
            json={"answers": {"q1": answers}},
            headers=student,
        )
        assert r.status_code == 200, r.text

    rows = (
        await db_session.execute(
            select(QuizAttempt)
            .where(QuizAttempt.lesson_id == lesson_id)
            .order_by(QuizAttempt.created_at.asc())
        )
    ).scalars().all()
    assert len(rows) == 3
    assert [a.passed for a in rows] == [False, False, True]
    # answers JSONB must hold the verbatim submission so a future
    # "review your attempt" UI can render it.
    assert rows[0].answers == {"q1": ["b"]}
    assert rows[-1].answers == {"q1": ["a"]}


async def test_listing_returns_newest_first_for_owner_only(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    me = await auth_headers(role=Role.student)
    other = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, lesson_id = await _quiz_lesson(client, teacher, subject.id)

    # Both students attempt the quiz.
    for headers in (me, other):
        await client.post(f"/api/v1/me/enrollments/{course_id}", headers=headers)
    for headers, ans in [(me, ["a"]), (me, ["b"]), (other, ["a"])]:
        await client.post(
            f"/api/v1/me/progress/lessons/{lesson_id}/quiz",
            json={"answers": {"q1": ans}},
            headers=headers,
        )

    r = await client.get(
        f"/api/v1/me/progress/lessons/{lesson_id}/quiz/attempts",
        headers=me,
    )
    assert r.status_code == 200
    body = r.json()
    # 2 attempts for `me`; the other student's attempt must NOT leak.
    assert len(body) == 2
    # Newest first.
    assert body[0]["submitted_at"] >= body[1]["submitted_at"]

    # Sanity: `other` sees their own one attempt only.
    r2 = await client.get(
        f"/api/v1/me/progress/lessons/{lesson_id}/quiz/attempts",
        headers=other,
    )
    assert len(r2.json()) == 1


async def test_attempts_empty_when_never_enrolled(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    visitor = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    _course_id, lesson_id = await _quiz_lesson(client, teacher, subject.id)

    r = await client.get(
        f"/api/v1/me/progress/lessons/{lesson_id}/quiz/attempts",
        headers=visitor,
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_attempts_404_for_unknown_lesson(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    r = await client.get(
        "/api/v1/me/progress/lessons/nope/quiz/attempts", headers=h
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "lesson.not_found"
