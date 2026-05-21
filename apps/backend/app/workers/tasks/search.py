"""Search index maintenance."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.base import get_sessionmaker
from app.models.course import Course, CourseStatus
from app.services.search import search_service
from app.workers.celery_app import celery

log = get_logger(__name__)


@celery.task(name="app.workers.tasks.search.reindex_catalog")
def reindex_catalog() -> None:
    asyncio.run(_reindex())


async def _reindex() -> None:
    search_service.ensure_index()
    Session = get_sessionmaker()
    async with Session() as db:
        result = await db.execute(
            select(Course)
            .options(selectinload(Course.subject), selectinload(Course.owner), selectinload(Course.tags))
            .where(Course.status == CourseStatus.published, Course.deleted_at.is_(None))
        )
        docs = []
        for c in result.scalars().all():
            docs.append(
                {
                    "id": c.id,
                    "title": c.title,
                    "slug": c.slug,
                    "overview": c.overview,
                    "difficulty": c.difficulty.value,
                    "status": c.status.value,
                    "subject_slug": c.subject.slug,
                    "subject_title": c.subject.title,
                    "owner_name": c.owner.full_name or c.owner.email,
                    "tag_slugs": [t.slug for t in c.tags],
                    "tag_names": [t.name for t in c.tags],
                    "published_at": c.published_at.isoformat() if c.published_at else None,
                }
            )
    if docs:
        search_service.index_courses(docs)
    log.info("search_reindex_done", count=len(docs))


@celery.task(name="app.workers.tasks.search.index_course")
def index_course(course_id: str) -> None:
    asyncio.run(_index_one(course_id))


async def _index_one(course_id: str) -> None:
    Session = get_sessionmaker()
    async with Session() as db:
        course = await db.execute(
            select(Course)
            .options(selectinload(Course.subject), selectinload(Course.owner), selectinload(Course.tags))
            .where(Course.id == course_id)
        )
        c = course.scalar_one_or_none()
        if not c:
            search_service.delete_course(course_id)
            return
        if c.status != CourseStatus.published or c.deleted_at is not None:
            search_service.delete_course(c.id)
            return
        search_service.index_courses(
            [
                {
                    "id": c.id,
                    "title": c.title,
                    "slug": c.slug,
                    "overview": c.overview,
                    "difficulty": c.difficulty.value,
                    "status": c.status.value,
                    "subject_slug": c.subject.slug,
                    "subject_title": c.subject.title,
                    "owner_name": c.owner.full_name or c.owner.email,
                    "tag_slugs": [t.slug for t in c.tags],
                    "tag_names": [t.name for t in c.tags],
                    "published_at": c.published_at.isoformat() if c.published_at else None,
                }
            ]
        )
