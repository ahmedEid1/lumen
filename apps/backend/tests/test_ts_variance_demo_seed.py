"""TS Generics/Variance demo seed (L20.5).

Asserts the course can be applied idempotently and lands with the
expected module + lesson structure so the canonical-error lesson is in
predictable position. The frontend `/demo` route slug-matches on
"canonical error" to pick the lesson to land on — that match needs the
title to stay stable across re-seeds.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, Lesson, Module, Subject, Tag
from app.models.user import Role, User
from app.seeds.ts_variance_demo import TS_VARIANCE_MODULES, apply


@pytest.mark.asyncio
async def test_ts_variance_seed_creates_expected_structure(
    db_session: AsyncSession,
) -> None:
    # Set up the prerequisites the seed assumes the parent demo bundle
    # already created: a programming subject, the typescript + demo
    # tags, and an instructor user.
    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    typescript_tag = Tag(slug="typescript", name="TypeScript")
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add_all([typescript_tag, demo_tag])

    from app.core.security import hash_password

    instructor = User(
        email="ts-instructor@lumen.test",
        password_hash=hash_password("Teach!2026"),
        full_name="TS Instructor",
        role=Role.instructor,
    )
    db_session.add(instructor)
    await db_session.flush()

    tags = {"typescript": typescript_tag, "demo": demo_tag}

    # Apply the seed and confirm idempotency on a second call.
    course = await apply(
        db_session, instructor=instructor, programming=programming, tags=tags
    )
    again = await apply(
        db_session, instructor=instructor, programming=programming, tags=tags
    )
    assert course.id == again.id, "apply() must be idempotent on re-run"

    assert course.slug == "typescript-variance"
    assert course.title == "TypeScript Generics & Variance"
    assert course.status.value == "published"

    # Module + lesson tree matches the in-module spec count for
    # confidence that nothing got dropped silently during _build.
    expected_module_count = len(TS_VARIANCE_MODULES)
    expected_lesson_count = sum(
        len(m["lessons"]) for m in TS_VARIANCE_MODULES
    )

    modules_res = await db_session.execute(
        select(Module).where(Module.course_id == course.id).order_by(Module.order)
    )
    modules = list(modules_res.scalars().all())
    assert len(modules) == expected_module_count

    lesson_count = 0
    canonical_error_titles: list[str] = []
    for module in modules:
        lessons_res = await db_session.execute(
            select(Lesson)
            .where(Lesson.module_id == module.id)
            .order_by(Lesson.order)
        )
        for lesson in lessons_res.scalars().all():
            lesson_count += 1
            if "canonical error" in lesson.title.lower():
                canonical_error_titles.append(lesson.title)

    assert lesson_count == expected_lesson_count

    # The /demo deep-link relies on the substring "canonical error"
    # matching exactly one lesson — locking that down here so a
    # well-meaning lesson rename can't silently break the demo flow.
    assert len(canonical_error_titles) == 1, (
        f"Expected exactly one 'canonical error' lesson; got {canonical_error_titles}"
    )


@pytest.mark.asyncio
async def test_ts_variance_seed_returns_existing_course_when_called_twice(
    db_session: AsyncSession,
) -> None:
    """A second `apply()` against a populated DB returns the same Course
    instance instead of creating duplicates — the seed's idempotency
    guarantee."""
    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    typescript_tag = Tag(slug="typescript", name="TypeScript")
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add_all([typescript_tag, demo_tag])

    from app.core.security import hash_password

    instructor = User(
        email="ts-instructor-2@lumen.test",
        password_hash=hash_password("Teach!2026"),
        full_name="TS Instructor 2",
        role=Role.instructor,
    )
    db_session.add(instructor)
    await db_session.flush()

    tags = {"typescript": typescript_tag, "demo": demo_tag}

    first = await apply(
        db_session, instructor=instructor, programming=programming, tags=tags
    )
    courses_after_first = await db_session.execute(
        select(Course).where(Course.slug == "typescript-variance")
    )
    assert len(list(courses_after_first.scalars().all())) == 1

    second = await apply(
        db_session, instructor=instructor, programming=programming, tags=tags
    )
    assert second.id == first.id

    courses_after_second = await db_session.execute(
        select(Course).where(Course.slug == "typescript-variance")
    )
    assert len(list(courses_after_second.scalars().all())) == 1, (
        "Second apply() must not create a duplicate course row"
    )
