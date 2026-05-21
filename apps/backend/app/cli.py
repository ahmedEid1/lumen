"""Lumen CLI — admin tasks, seed, reindex."""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC

import typer
from rich.console import Console
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import get_sessionmaker
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Enrollment,
    Lesson,
    LessonType,
    Module,
    Subject,
    Tag,
)
from app.models.user import Role, User

cli = typer.Typer(no_args_is_help=True)
console = Console()


@cli.command()
def bootstrap_admin(email: str = "admin@lumen.test", password: str = "Admin!2026", full_name: str = "Admin") -> None:
    """Create or upsert an admin user."""
    asyncio.run(_bootstrap_admin(email, password, full_name))


async def _bootstrap_admin(email: str, password: str, full_name: str) -> None:
    Session = get_sessionmaker()
    async with Session() as db:
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if user:
            user.role = Role.admin
            user.is_active = True
            user.full_name = full_name
            await db.commit()
            console.print(f"[green]Updated existing user {email} → admin[/green]")
            return
        u = User(email=email, password_hash=hash_password(password), full_name=full_name, role=Role.admin)
        db.add(u)
        await db.commit()
        console.print(f"[green]Created admin {email}[/green]")


@cli.command()
def seed() -> None:
    """Load demo subjects, tags, instructor, student, and a course."""
    asyncio.run(_seed())


async def _seed() -> None:  # noqa: PLR0915
    Session = get_sessionmaker()
    async with Session() as db:
        # Subjects
        subjects = {}
        for title, slug in [
            ("Programming", "programming"),
            ("Data Science", "data-science"),
            ("Design", "design"),
            ("Business", "business"),
            ("Mathematics", "mathematics"),
        ]:
            res = await db.execute(select(Subject).where(Subject.slug == slug))
            s = res.scalar_one_or_none()
            if not s:
                s = Subject(title=title, slug=slug)
                db.add(s)
                await db.flush()
            subjects[slug] = s

        # Tags
        tags = {}
        for name, slug in [
            ("Beginner", "beginner"),
            ("Python", "python"),
            ("FastAPI", "fastapi"),
            ("React", "react"),
            ("TypeScript", "typescript"),
            ("Machine Learning", "machine-learning"),
            ("Algorithms", "algorithms"),
            ("UX", "ux"),
        ]:
            res = await db.execute(select(Tag).where(Tag.slug == slug))
            t = res.scalar_one_or_none()
            if not t:
                t = Tag(name=name, slug=slug)
                db.add(t)
                await db.flush()
            tags[slug] = t

        # Users
        users = {
            "admin@lumen.test": ("Admin", Role.admin, "Admin!2026"),
            "teacher@lumen.test": ("Tareq Hassan", Role.instructor, "Teach!2026"),
            "student@lumen.test": ("Lina Park", Role.student, "Learn!2026"),
        }
        created = {}
        for email, (full_name, role, password) in users.items():
            res = await db.execute(select(User).where(User.email == email))
            user = res.scalar_one_or_none()
            if not user:
                user = User(email=email, password_hash=hash_password(password), full_name=full_name, role=role)
                db.add(user)
                await db.flush()
            created[email] = user

        instructor = created["teacher@lumen.test"]
        student = created["student@lumen.test"]

        # Course
        existing = await db.execute(select(Course).where(Course.slug == "fastapi-from-zero"))
        course = existing.scalar_one_or_none()
        if not course:
            course = Course(
                owner_id=instructor.id,
                subject_id=subjects["programming"].id,
                title="FastAPI from Zero",
                slug="fastapi-from-zero",
                overview="Learn to build production-ready APIs with FastAPI, SQLAlchemy 2, and async Python.",
                difficulty=Difficulty.beginner,
                cover_url=None,
                status=CourseStatus.published,
                published_at=datetime.now(UTC),
                is_featured=True,
            )
            course.tags = [tags["python"], tags["fastapi"], tags["beginner"]]
            db.add(course)
            await db.flush()

            module1 = Module(course_id=course.id, title="Getting started", description="The why and the how.", order=0)
            module2 = Module(course_id=course.id, title="Routing & schemas", description="Pydantic + path & query.", order=1)
            module3 = Module(course_id=course.id, title="Persistence", description="Async SQLAlchemy.", order=2)
            db.add_all([module1, module2, module3])
            await db.flush()

            db.add_all([
                Lesson(
                    module_id=module1.id, title="Welcome", type=LessonType.text, order=0,
                    data={"type": "text", "body_markdown": "Welcome to *FastAPI from Zero*. Let's build something!"},
                ),
                Lesson(
                    module_id=module1.id, title="Project layout", type=LessonType.text, order=1,
                    data={"type": "text", "body_markdown": "We'll structure the project with clear seams between layers."},
                ),
                Lesson(
                    module_id=module2.id, title="Path & query params", type=LessonType.text, order=0,
                    data={"type": "text", "body_markdown": "FastAPI infers OpenAPI from your type hints."},
                ),
                Lesson(
                    module_id=module2.id, title="Quick quiz", type=LessonType.quiz, order=1,
                    data={
                        "type": "quiz",
                        "pass_score": 60,
                        "questions": [
                            {
                                "id": "q1",
                                "prompt": "Which library provides FastAPI's data validation?",
                                "kind": "single",
                                "choices": [
                                    {"id": "a", "text": "marshmallow"},
                                    {"id": "b", "text": "pydantic"},
                                    {"id": "c", "text": "attrs"},
                                ],
                                "answer_keys": ["b"],
                            }
                        ],
                    },
                ),
                Lesson(
                    module_id=module3.id, title="Async session", type=LessonType.text, order=0,
                    data={"type": "text", "body_markdown": "Use `AsyncSession` and let SQLAlchemy 2 do the heavy lifting."},
                ),
            ])
            await db.flush()

            db.add(Enrollment(user_id=student.id, course_id=course.id))

        await db.commit()
        console.print("[green]Seeded demo data[/green]")


@cli.command()
def reindex() -> None:
    """Reindex the search backend."""
    from app.workers.tasks.search import _reindex

    asyncio.run(_reindex())


@cli.command()
def info() -> None:
    """Print configuration summary."""
    s = get_settings()
    console.print(
        {
            "env": s.env,
            "api": str(s.api_base_url),
            "db": s.database_url,
            "redis": s.redis_url,
            "search": s.search_backend,
            "s3": s.s3_endpoint_url,
        }
    )


if __name__ == "__main__":  # pragma: no cover
    cli()
