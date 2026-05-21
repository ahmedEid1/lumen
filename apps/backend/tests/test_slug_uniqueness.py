"""Regression: slug minting must collide-detect against soft-deleted rows.

Before iteration 25, ``_unique_slug`` looked up candidates through
``get_course_by_slug``, which already filtered ``deleted_at IS NOT NULL``.
A second course created with the same title as a soft-deleted course
appeared free to the slug minter, then the INSERT crashed against the
unconditional ``UNIQUE(courses.slug)`` constraint.
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


async def test_recreating_a_deleted_courses_title_picks_a_fresh_slug(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)

    first = await client.post(
        "/api/v1/courses",
        json={"title": "Quantum mechanics", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    assert first.status_code == 201
    first_slug = first.json()["slug"]
    first_id = first.json()["id"]

    # Soft-delete it
    deleted = await client.delete(f"/api/v1/courses/{first_id}", headers=teacher)
    assert deleted.status_code == 200

    # Create another course with the exact same title — slug must collide-
    # detect against the soft-deleted row, not raise UniqueViolation.
    second = await client.post(
        "/api/v1/courses",
        json={"title": "Quantum mechanics", "subject_id": subject.id, "overview": "y"},
        headers=teacher,
    )
    assert second.status_code == 201, second.text
    assert second.json()["slug"] != first_slug


async def test_duplicating_a_course_uses_a_fresh_slug(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Original", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    original_id = create.json()["id"]
    original_slug = create.json()["slug"]

    dup1 = await client.post(f"/api/v1/courses/{original_id}/duplicate", headers=teacher)
    dup2 = await client.post(f"/api/v1/courses/{original_id}/duplicate", headers=teacher)
    assert dup1.status_code == 201 and dup2.status_code == 201
    slugs = {original_slug, dup1.json()["slug"], dup2.json()["slug"]}
    assert len(slugs) == 3, slugs


async def test_renaming_keeps_slug_when_unchanged(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Renaming back to the current title must not pick a sibling slug
    just because the row exists. ``exclude_id`` is the guard."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Stable name", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    original_slug = create.json()["slug"]

    # PATCH to the same title — should be a no-op for the slug
    patch = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"title": "Stable name"},
        headers=teacher,
    )
    assert patch.status_code == 200
    assert patch.json()["slug"] == original_slug
