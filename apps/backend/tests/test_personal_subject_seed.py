"""S3.5 — reserved Personal/Self-directed Subject seed (FR-DEFINE-12, NFR-MIG-3).

The self-serve build attaches to a reserved Subject when the learner's
suggested subject matches no live admin-curated Subject — the escape from
``authoring.subject_not_found``. The seed must be idempotent (the migration's
``ON CONFLICT (slug) DO NOTHING`` + the demo seed's ``get_or_create``) so a
fresh migrate, a re-migrate, or a double-seed all converge to exactly one row
(``Subject.slug`` is unique).

The migration (0051) has already run against the test DB via conftest's
``metadata.create_all`` path is NOT used for data rows — the migration's data
insert only runs under real Alembic, which the integration DB applied. To keep
this test self-contained against the conftest schema-only DB, it drives the
**seed helper** (``demo._get_or_create``) directly and asserts idempotency,
mirroring how the migration's ON CONFLICT behaves.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.course import Subject
from app.seeds import demo

pytestmark = pytest.mark.asyncio


async def _count_personal(db) -> int:
    slug = get_settings().personal_subject_slug
    return (
        await db.execute(select(func.count()).select_from(Subject).where(Subject.slug == slug))
    ).scalar_one()


async def test_seed_creates_exactly_one_personal_subject(db_session):
    slug = get_settings().personal_subject_slug

    obj, created = await demo._get_or_create(
        db_session,
        Subject,
        lookup={"slug": slug},
        defaults={"title": "Personal / Self-directed"},
    )
    await db_session.commit()

    assert created is True
    assert obj.slug == slug
    assert obj.title == "Personal / Self-directed"
    assert await _count_personal(db_session) == 1


async def test_seed_is_idempotent_on_rerun(db_session):
    """Running the seed twice does NOT create a duplicate (NFR-MIG-3)."""
    slug = get_settings().personal_subject_slug

    first, created_first = await demo._get_or_create(
        db_session, Subject, lookup={"slug": slug}, defaults={"title": "Personal / Self-directed"}
    )
    await db_session.commit()
    second, created_second = await demo._get_or_create(
        db_session, Subject, lookup={"slug": slug}, defaults={"title": "Personal / Self-directed"}
    )
    await db_session.commit()

    assert created_first is True
    assert created_second is False  # idempotent — found the existing row
    assert second.id == first.id
    assert await _count_personal(db_session) == 1


async def test_personal_subject_slug_default():
    """The reserved slug is configured (consumed by S3.6 subject auto-resolve)."""
    assert get_settings().personal_subject_slug == "personal-self-directed"
