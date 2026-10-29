"""L14: course detail must not leak gated lesson bodies or quiz answers.
L64: reset, verify and email-change tokens must not work as logins."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, ModerationState, Subject, Visibility
from app.models.user import Role
from app.services import email_change, email_verify, password_reset

SECRET_BODY = "Only enrolled learners may read this paragraph."
QUIZ = {
    "type": "quiz",
    "pass_score": 60,
    "questions": [
        {
            "id": "q1",
            "prompt": "Pick b",
            "kind": "single",
            "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            "answer_keys": ["b"],
        }
    ],
}


async def _listed_course(client: AsyncClient, headers: dict, db: AsyncSession) -> str:
    subject = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(subject)
    await db.commit()
    course_id = (
        await client.post(
            "/api/v1/courses",
            json={"title": "Gated", "subject_id": subject.id, "overview": "x"},
            headers=headers,
        )
    ).json()["id"]
    module_id = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=headers
        )
    ).json()["id"]
    lessons = [
        {
            "title": "Preview",
            "type": "text",
            "is_preview": True,
            "data": {"type": "text", "body_markdown": "Free preview text."},
        },
        {"title": "Gated", "type": "text", "data": {"type": "text", "body_markdown": SECRET_BODY}},
        {"title": "Quiz", "type": "quiz", "data": QUIZ},
    ]
    for body in lessons:
        r = await client.post(
            f"/api/v1/courses/modules/{module_id}/lessons", json=body, headers=headers
        )
        assert r.status_code == 201, r.text
    await db.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(
            status=CourseStatus.published,
            visibility=Visibility.public,
            moderation_state=ModerationState.approved,
        )
    )
    await db.commit()
    return course_id


def _lessons(detail: dict) -> dict[str, dict]:
    return {lsn["title"]: lsn for m in detail["modules"] for lsn in m["lessons"]}


async def test_anonymous_detail_hides_gated_bodies_and_answer_keys(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    owner = await auth_headers(role=Role.instructor)
    course_id = await _listed_course(client, owner, db_session)

    # The test client keeps the login cookie; drop it to call anonymously.
    client.cookies.clear()
    anon = await client.get(f"/api/v1/courses/{course_id}")
    assert anon.status_code == 200, anon.text
    assert SECRET_BODY not in anon.text
    assert "answer_keys" not in anon.text
    lessons = _lessons(anon.json())
    assert lessons["Gated"]["data"] == {"type": "text"}
    assert lessons["Quiz"]["data"] == {"type": "quiz"}
    # The free preview stays readable, as GET /lessons/{id} allows.
    assert lessons["Preview"]["data"]["body_markdown"] == "Free preview text."

    # A signed-in stranger who hasn't enrolled gets the same syllabus.
    stranger = await auth_headers(role=Role.student)
    r = await client.get(f"/api/v1/courses/{course_id}", headers=stranger)
    assert r.json()["can_publish_public"] is None  # really not the owner
    assert SECRET_BODY not in r.text
    assert "answer_keys" not in r.text

    # The owner still sees everything (studio and learn read this endpoint).
    r = await client.get(f"/api/v1/courses/{course_id}", headers=owner)
    assert SECRET_BODY in r.text
    assert "answer_keys" in r.text


async def test_enrolled_learner_reads_full_lessons(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    owner = await auth_headers(role=Role.instructor)
    course_id = await _listed_course(client, owner, db_session)
    learner = await auth_headers(role=Role.student)
    enrolled = await client.post(f"/api/v1/me/enrollments/{course_id}", headers=learner)
    assert enrolled.status_code in (200, 201), enrolled.text

    r = await client.get(f"/api/v1/courses/{course_id}", headers=learner)
    assert r.json()["is_enrolled"] is True
    assert SECRET_BODY in r.text


@pytest.mark.parametrize("kind", ["pw-reset", "email-verify", "email-change"])
async def test_purpose_tokens_are_not_logins(client: AsyncClient, make_user, kind: str) -> None:
    user = await make_user(email=f"tok-{uuid.uuid4().hex[:8]}@lumen.test")
    if kind == "pw-reset":
        token = password_reset.make_token(user)
    elif kind == "email-verify":
        token = email_verify.make_token(user)
    else:
        token = email_change.make_token(user, new_email=f"new-{uuid.uuid4().hex[:6]}@lumen.test")

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, r.text
