"""Regression: ``?sort=…`` must be allow-listed.

Before iteration 29, the catalog repo resolved ``sort`` via
``getattr(Course, field_name)``. Crafted values like ``sort=modules``
(relationship), ``sort=metadata`` (SQLAlchemy bookkeeping), or
``sort=__class__`` (dunder) returned non-column attributes whose
``.desc()`` raised ``AttributeError`` and surfaced as a 500. The
allow-list now picks ``Course.created_at`` for any unrecognised value
so the catalog never crashes from a query string.
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


async def _publish(
    client: AsyncClient, headers: dict, subject_id: str, title: str, seed_lesson, db: AsyncSession
) -> None:
    """Create + seed + publish AND publicly list (S2 / ADR-0026).

    ``PATCH {status: "published"}`` is now a 422 (lifecycle moved to
    ``POST /courses/{id}/publish``), and publishing keeps a course private.
    Catalog reads only surface ``is_publicly_listed`` courses, so drive all
    three axes to the publicly-listed state via the DB session — mirroring
    S2's own ``_mk_course`` helper.
    """
    from sqlalchemy import update

    from app.models.course import Course, CourseStatus, ModerationState, Visibility

    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, headers)
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


async def _seed(client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    await _publish(client, teacher, subject.id, "Alpha", seed_lesson, db_session)
    await _publish(client, teacher, subject.id, "Bravo", seed_lesson, db_session)


async def test_unknown_sort_does_not_crash(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    await _seed(client, auth_headers, db_session, seed_lesson)
    # ``modules`` is a relationship attribute on Course — was crashy
    r = await client.get("/api/v1/courses?sort=modules")
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) >= 2


async def test_dunder_sort_does_not_crash(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    await _seed(client, auth_headers, db_session, seed_lesson)
    r = await client.get("/api/v1/courses?sort=__class__")
    assert r.status_code == 200


async def test_known_sort_keys_work(
    client: AsyncClient, auth_headers, db_session: AsyncSession, seed_lesson
) -> None:
    await _seed(client, auth_headers, db_session, seed_lesson)
    for sort in ("-created_at", "created_at", "-published_at", "title", "-is_featured"):
        r = await client.get(f"/api/v1/courses?sort={sort}")
        assert r.status_code == 200, f"{sort=} → {r.status_code} {r.text}"
