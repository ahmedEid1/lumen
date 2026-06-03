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
    h = await auth_headers(role=Role.user)
    r = await client.get("/api/v1/admin/stats", headers=h)
    assert r.status_code == 403


async def test_platform_stats_reports_admins_and_authors(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    # S1.8 / FR-ADMIN-05: the `instructors` stat is replaced by `admins`
    # (admin-role users) + `authors` (distinct owners of a live course).
    admin = await auth_headers(role=Role.admin)
    author = await auth_headers(role=Role.user)
    learner = await auth_headers(role=Role.user)
    subject = await _make_subject(db_session)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "S", "subject_id": subject.id, "overview": "x"},
        headers=author,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, author)
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=author)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=learner)

    r = await client.get("/api/v1/admin/stats", headers=admin)
    assert r.status_code == 200
    body = r.json()
    # The legacy `instructors` field is gone; admins/authors are present.
    assert "instructors" not in body
    assert "admins" in body and "authors" in body
    # We don't pin exact counts (fixtures create users across tests), but
    # the relationships hold: at least one admin, at least one author.
    assert body["users"] >= 3
    assert body["active_users"] >= 3
    assert body["admins"] >= 1
    assert body["authors"] >= 1
    assert body["courses_total"] >= 1
    assert body["courses_published"] >= 1
    assert body["enrollments"] >= 1
