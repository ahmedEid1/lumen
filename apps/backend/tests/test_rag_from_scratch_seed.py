"""RAG-from-scratch demo seed (L20.6)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, Lesson, Module, Subject, Tag
from app.models.user import Role, User
from app.seeds.rag_from_scratch_demo import RAG_FROM_SCRATCH_MODULES, apply


@pytest.mark.asyncio
async def test_rag_seed_creates_expected_structure(db_session: AsyncSession) -> None:
    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add(demo_tag)

    from app.core.security import hash_password

    instructor = User(
        email="rag-instructor@lumen.test",
        password_hash=hash_password("Teach!2026"),
        full_name="RAG Instructor",
        role=Role.instructor,
    )
    db_session.add(instructor)
    await db_session.flush()

    tags = {"demo": demo_tag}

    course = await apply(db_session, instructor=instructor, programming=programming, tags=tags)
    again = await apply(db_session, instructor=instructor, programming=programming, tags=tags)
    assert course.id == again.id

    assert course.slug == "rag-from-scratch"
    assert course.title == "Building a RAG system from scratch"

    expected_module_count = len(RAG_FROM_SCRATCH_MODULES)
    expected_lesson_count = sum(len(m["lessons"]) for m in RAG_FROM_SCRATCH_MODULES)

    modules_res = await db_session.execute(
        select(Module).where(Module.course_id == course.id).order_by(Module.order)
    )
    modules = list(modules_res.scalars().all())
    assert len(modules) == expected_module_count

    lesson_count = 0
    for module in modules:
        lessons_res = await db_session.execute(select(Lesson).where(Lesson.module_id == module.id))
        lesson_count += len(list(lessons_res.scalars().all()))
    assert lesson_count == expected_lesson_count


@pytest.mark.asyncio
async def test_rag_seed_is_idempotent(db_session: AsyncSession) -> None:
    programming = Subject(slug="programming", title="Programming")
    db_session.add(programming)
    demo_tag = Tag(slug="demo", name="Demo")
    db_session.add(demo_tag)

    from app.core.security import hash_password

    instructor = User(
        email="rag-instructor-2@lumen.test",
        password_hash=hash_password("Teach!2026"),
        full_name="RAG Instructor 2",
        role=Role.instructor,
    )
    db_session.add(instructor)
    await db_session.flush()

    tags = {"demo": demo_tag}

    first = await apply(db_session, instructor=instructor, programming=programming, tags=tags)
    second = await apply(db_session, instructor=instructor, programming=programming, tags=tags)
    assert first.id == second.id

    courses = await db_session.execute(select(Course).where(Course.slug == "rag-from-scratch"))
    assert len(list(courses.scalars().all())) == 1
