"""Server-side quiz grading + the /me/progress/.../quiz endpoint."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role
from app.services import quiz as quiz_service

# ---------- pure grader ----------


def _q_single():
    return {
        "id": "q1",
        "prompt": "Pick A",
        "kind": "single",
        "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
        "answer_keys": ["a"],
    }


def _q_multi():
    return {
        "id": "q2",
        "prompt": "Pick A and B",
        "kind": "multiple",
        "choices": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "answer_keys": ["a", "b"],
    }


def _q_short():
    return {
        "id": "q3",
        "prompt": "Capital of France?",
        "kind": "short",
        "answer_keys": ["Paris"],
    }


def _data(pass_score=60, *questions):
    return {"pass_score": pass_score, "questions": list(questions)}


def test_grade_all_correct():
    res = quiz_service.grade(
        _data(60, _q_single(), _q_multi(), _q_short()),
        {"q1": ["a"], "q2": ["b", "a"], "q3": "Paris"},
    )
    assert res.score == 100
    assert res.correct_count == 3
    assert res.total == 3
    assert res.passed is True


def test_grade_partial_below_threshold():
    res = quiz_service.grade(
        _data(80, _q_single(), _q_multi(), _q_short()),
        {"q1": ["a"], "q2": ["a"], "q3": "wrong"},
    )
    assert res.score == 33
    assert res.passed is False


def test_grade_short_answer_case_insensitive():
    res = quiz_service.grade(_data(50, _q_short()), {"q3": "  paris  "})
    assert res.score == 100


def test_grade_multiple_count_sensitive():
    # Extra correct answers should fail the question
    res = quiz_service.grade(_data(50, _q_multi()), {"q2": ["a", "b", "c"]})
    assert res.score == 0


def test_grade_handles_missing_answer():
    res = quiz_service.grade(_data(50, _q_single()), {})
    assert res.score == 0
    assert res.results[0].correct is False


def test_grade_empty_quiz():
    res = quiz_service.grade(_data(60), {})
    assert res.score == 0
    assert res.total == 0
    assert res.passed is False


# ---------- endpoint ----------


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _quiz_course(client: AsyncClient, teacher: dict, subject_id: str) -> tuple[str, str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Quizzy", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
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
                },
            },
            headers=teacher,
        )
    ).json()
    text_lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "Hello", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    return course_id, lesson["id"], text_lesson["id"]


async def test_quiz_endpoint_grades_and_marks_complete(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id, _ = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    pass_attempt = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student,
    )
    assert pass_attempt.status_code == 200, pass_attempt.text
    body = pass_attempt.json()
    assert body["score"] == 100
    assert body["passed"] is True
    assert body["completed_at"] is not None
    assert body["results"][0]["correct"] is True


async def test_quiz_endpoint_fails_below_threshold(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id, _ = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    fail_attempt = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["b"]}},
        headers=student,
    )
    assert fail_attempt.status_code == 200
    body = fail_attempt.json()
    assert body["score"] == 0
    assert body["passed"] is False
    assert body["completed_at"] is None


async def test_quiz_endpoint_rejects_non_quiz_lesson(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, _, text_id = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    r = await client.post(
        f"/api/v1/me/progress/lessons/{text_id}/quiz",
        json={"answers": {}},
        headers=student,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "quiz.not_a_quiz"


async def test_quiz_endpoint_unknown_lesson_404(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/me/progress/lessons/nope/quiz",
        json={"answers": {}},
        headers=h,
    )
    assert r.status_code == 404
