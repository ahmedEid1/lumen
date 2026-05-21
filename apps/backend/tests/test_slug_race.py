"""Regression: concurrent course creation with the same title must not 500.

Before iteration 49 ``_unique_slug`` ran a non-locking SELECT and
returned the first free candidate. Two requests that picked the same
slug (the obvious one for the given title) both passed the check; the
second INSERT collided on ``UNIQUE(courses.slug)`` and surfaced as a
generic 500.

The fix wraps the INSERT in a SAVEPOINT and retries with a short
random suffix on ``IntegrityError`` — keeping the outer transaction
clean (no rollback of subject lookups / tag attachments / audit
records the request did before the create).

We simulate the race deterministically by pre-seeding a course with
the slug a fresh create would otherwise mint, then asserting the
second create succeeds with a disambiguated slug rather than 5xx.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, CourseStatus, Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_create_recovers_when_obvious_slug_already_claimed(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    teacher_a = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    # Seed a course that already owns the slug a fresh "Async Python"
    # create would otherwise pick. This is the same outcome as the race
    # where another request beat us to the INSERT.
    db_session.add(
        Course(
            owner_id=teacher_a.id,
            subject_id=subject.id,
            title="Pre-existing",
            slug="async-python",
            overview="seeded",
            status=CourseStatus.draft,
        )
    )
    await db_session.commit()

    teacher_b = await auth_headers(role=Role.instructor)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Async Python", "subject_id": subject.id, "overview": "x"},
        headers=teacher_b,
    )
    # Before iter 49 this would have failed in the second INSERT (the
    # collision-safe loop in _unique_slug would have appended -2, but the
    # race scenario where two requests both pick the same "-2" suffix
    # would still 500). Now the create succeeds with a disambiguated
    # slug — either "async-python-2" from the natural loop, or
    # "async-python-<random>" from the savepoint-retry fallback.
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"].startswith("async-python")
    assert body["slug"] != "async-python"


async def test_savepoint_retry_succeeds_even_when_n2_also_taken(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    """Pre-claim both the obvious slug AND the -2 fallback. The
    natural loop would still find "-3" so we don't actually hit the
    IntegrityError branch here — but we verify the result is sane and
    that nothing 5xx'd."""
    teacher_a = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    for slug in ("crowded", "crowded-2"):
        db_session.add(
            Course(
                owner_id=teacher_a.id,
                subject_id=subject.id,
                title=slug,
                slug=slug,
                overview="seeded",
                status=CourseStatus.draft,
            )
        )
    await db_session.commit()

    teacher_b = await auth_headers(role=Role.instructor)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Crowded", "subject_id": subject.id, "overview": "x"},
        headers=teacher_b,
    )
    assert r.status_code == 201, r.text
    assert r.json()["slug"].startswith("crowded")
    assert r.json()["slug"] not in {"crowded", "crowded-2"}


async def test_update_rename_recovers_from_slug_collision(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user
) -> None:
    """Renaming a course to a title whose obvious slug is already
    claimed must not 500 on the request-end commit. update_course
    minted the new slug via the racy SELECT but never flushed; the
    collision used to surface as an unhandled IntegrityError when the
    dependency-override committed at request end."""
    placeholder_owner = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    # Pre-claim the slug a "Renamed Course" PATCH would otherwise mint.
    db_session.add(
        Course(
            owner_id=placeholder_owner.id,
            subject_id=subject.id,
            title="placeholder",
            slug="renamed-course",
            overview="x",
            status=CourseStatus.draft,
        )
    )
    await db_session.commit()

    teacher = await auth_headers(role=Role.instructor)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Original", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]

    # Rename collides with the seeded slug.
    r = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"title": "Renamed Course"},
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed Course"
    assert r.json()["slug"].startswith("renamed-course")
    assert r.json()["slug"] != "renamed-course"


async def test_duplicate_also_recovers_from_slug_collision(
    client: AsyncClient, auth_headers, db_session: AsyncSession, make_user, seed_lesson
) -> None:
    """Duplicate path goes through the same _flush_course_with_slug_retry
    helper, so a busy slug for ``"Foo (copy)"`` shouldn't 500 the dup."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Foo", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await seed_lesson(course_id, teacher)
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )

    # Pre-claim the natural duplicate slug ("foo-copy").
    placeholder_owner = await make_user(role=Role.instructor)
    db_session.add(
        Course(
            owner_id=placeholder_owner.id,
            subject_id=subject.id,
            title="placeholder",
            slug="foo-copy",
            overview="x",
            status=CourseStatus.draft,
        )
    )
    await db_session.commit()

    r = await client.post(f"/api/v1/courses/{course_id}/duplicate", headers=teacher)
    assert r.status_code == 201, r.text
    assert r.json()["slug"].startswith("foo-copy")
    assert r.json()["slug"] != "foo-copy"
