"""Regression: failing a quiz retake must not un-pass an earlier pass.

Before iteration 23 the quiz endpoint reused ``mark_lesson(completed=…)``,
which cleared ``LessonProgress.completed_at`` whenever the latest attempt
failed. The result: a learner who passed, then retook out of curiosity
and scored low, lost their completion (and any course-level certificate
implication that followed). The dedicated ``record_quiz_attempt`` service
now preserves completion across retakes.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role

PASS_ANSWERS = {"q1": ["a"]}
FAIL_ANSWERS = {"q1": ["b"]}

QUIZ_DATA = {
    "type": "quiz",
    "pass_score": 60,
    "questions": [
        {
            "id": "q1",
            "prompt": "Pick A",
            "kind": "single",
            "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            "answer_keys": ["a"],
        }
    ],
}


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _enroll_in_quiz_course(
    client: AsyncClient, headers_t: dict, headers_s: dict, subject_id: str, publish_and_list_course
) -> str:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Quizland", "subject_id": subject_id, "overview": "x"},
        headers=headers_t,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=headers_t
        )
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "Quiz", "type": "quiz", "data": QUIZ_DATA},
            headers=headers_t,
        )
    ).json()
    await publish_and_list_course(course_id, headers_t)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=headers_s)
    return lesson["id"]


async def test_quiz_retake_failure_does_not_clear_pass(
    client: AsyncClient, auth_headers, db_session: AsyncSession, publish_and_list_course
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    quiz_id = await _enroll_in_quiz_course(
        client, teacher, student, subject.id, publish_and_list_course
    )

    first = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": PASS_ANSWERS},
        headers=student,
    )
    assert first.status_code == 200
    body1 = first.json()
    assert body1["passed"] is True
    assert body1["completed_at"] is not None
    first_completed_at = body1["completed_at"]

    # Retake and fail
    second = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": FAIL_ANSWERS},
        headers=student,
    )
    assert second.status_code == 200
    body2 = second.json()
    assert body2["passed"] is False
    assert body2["score"] == 0
    # The lesson must remain complete — completed_at is preserved verbatim
    assert body2["completed_at"] == first_completed_at
    # And the progress % stays at 100% (one lesson, one completion)
    assert body2["progress_pct"] == 100.0


async def test_quiz_retake_records_latest_score_on_pass(
    client: AsyncClient, auth_headers, db_session: AsyncSession, publish_and_list_course
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    quiz_id = await _enroll_in_quiz_course(
        client, teacher, student, subject.id, publish_and_list_course
    )

    fail = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": FAIL_ANSWERS},
        headers=student,
    )
    assert fail.json()["passed"] is False
    assert fail.json()["completed_at"] is None

    win = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": PASS_ANSWERS},
        headers=student,
    )
    body = win.json()
    assert body["passed"] is True
    assert body["score"] == 100
    assert body["completed_at"] is not None
