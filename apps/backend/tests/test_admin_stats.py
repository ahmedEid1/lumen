"""Admin platform stats endpoint."""

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


async def test_stats_requires_admin(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers(role=Role.student)
    r = await client.get("/api/v1/admin/stats", headers=h)
    assert r.status_code == 403


async def test_stats_reflect_seeded_state(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    admin = await auth_headers(role=Role.admin)
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "S", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    # S2: publishing keeps a course PRIVATE (published-private self-learn). To
    # make it publicly listed (and so enrollable + counted in courses_listed)
    # set the share+approval state directly (the /share + admin /approve
    # endpoints land in S2.11 / S6).
    from sqlalchemy import update

    from app.models.course import Course, ModerationState, Visibility

    await db_session.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(visibility=Visibility.public, moderation_state=ModerationState.approved)
    )
    await db_session.commit()
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)

    r = await client.get("/api/v1/admin/stats", headers=admin)
    assert r.status_code == 200
    body = r.json()
    # We don't pin exact counts (auth_headers + make_user fixtures create users
    # opportunistically across tests), but the relationships should hold.
    assert body["users"] >= 3
    assert body["active_users"] >= 3
    assert body["instructors"] >= 2  # teacher + admin
    assert body["courses_total"] >= 1
    assert body["courses_published"] >= 1  # lifecycle count (incl. private)
    assert body["courses_listed"] >= 1  # publicly-listed count (S2.8)
    assert body["enrollments"] >= 1
