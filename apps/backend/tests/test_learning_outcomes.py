"""Course "What you'll learn" bullet list.

Iter 86 adds a JSONB ``learning_outcomes`` list to courses. Pydantic
trims whitespace, drops empties, caps each item at 240 chars, and
caps the list at 12 items (past that the section stops being a
conversion tool and starts being a wall of text).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role
from app.schemas.course import CourseCreate


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


# ---------- schema-level ----------


def test_schema_trims_and_drops_empties() -> None:
    cc = CourseCreate(
        title="X",
        subject_id="s1",
        learning_outcomes=["  Build REST APIs  ", "", "Deploy with Docker", "   "],
    )
    assert cc.learning_outcomes == ["Build REST APIs", "Deploy with Docker"]


def test_schema_rejects_item_over_240_chars() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(
            title="X",
            subject_id="s1",
            learning_outcomes=["x" * 241],
        )


def test_schema_rejects_more_than_12_items() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(
            title="X",
            subject_id="s1",
            learning_outcomes=[f"outcome {i}" for i in range(13)],
        )


# ---------- API round-trip ----------


async def test_create_and_get_with_outcomes(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={
            "title": "Real Python",
            "subject_id": subject.id,
            "overview": "x",
            "learning_outcomes": [
                "Write idiomatic Python",
                "Build a CLI",
                "Test with pytest",
            ],
        },
        headers=teacher,
    )
    assert create.status_code == 201, create.text

    detail = await client.get(f"/api/v1/courses/{create.json()['id']}", headers=teacher)
    assert detail.status_code == 200
    assert detail.json()["learning_outcomes"] == [
        "Write idiomatic Python",
        "Build a CLI",
        "Test with pytest",
    ]


async def test_patch_replaces_outcomes(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={
            "title": "Real Python",
            "subject_id": subject.id,
            "overview": "x",
            "learning_outcomes": ["A", "B"],
        },
        headers=teacher,
    )
    course_id = create.json()["id"]

    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"learning_outcomes": ["X", "Y", "Z"]},
        headers=teacher,
    )

    detail = await client.get(f"/api/v1/courses/{course_id}", headers=teacher)
    assert detail.json()["learning_outcomes"] == ["X", "Y", "Z"]


async def test_existing_course_starts_with_empty_outcomes(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Migration backfilled with [] — a course created without the
    new field reads as an empty list, never None / missing."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "No outcomes", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    detail = await client.get(f"/api/v1/courses/{create.json()['id']}", headers=teacher)
    assert detail.json()["learning_outcomes"] == []
