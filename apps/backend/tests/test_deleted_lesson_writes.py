"""Regression: progress writes against a soft-deleted lesson must 404.

Both ``POST /me/progress/lessons/{id}`` and the quiz submission used
``courses_repo.get_lesson`` which does not filter ``deleted_at``. So an
enrolled learner who held a stale lesson id (cached SPA state, replay
of a request, etc.) could create ``LessonProgress`` rows pointing at
lessons that were no longer part of the curriculum. The rows didn't
count toward progress (the count query is filtered) but they did clutter
the DB and surface a misleading 200 response.

Both endpoints now reject deleted-lesson writes with 404 ``lesson.not_found``.
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


async def _publish(client: AsyncClient, teacher: dict, subject_id: str) -> tuple[str, str, str]:
    create = await client.post(
        "/api/v1/courses",
        json={"title": "DeletedLesson", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
        )
    ).json()
    text_lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "T", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()
    quiz_lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Q",
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
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    return course_id, text_lesson["id"], quiz_lesson["id"]


async def test_mark_complete_404s_for_deleted_lesson(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, text_id, _ = await _publish(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    await client.delete(f"/api/v1/courses/lessons/{text_id}", headers=teacher)

    r = await client.post(
        f"/api/v1/me/progress/lessons/{text_id}",
        json={"completed": True},
        headers=student,
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "lesson.not_found"


async def test_quiz_submit_404s_for_deleted_lesson(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, _, quiz_id = await _publish(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    await client.delete(f"/api/v1/courses/lessons/{quiz_id}", headers=teacher)

    r = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student,
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "lesson.not_found"
