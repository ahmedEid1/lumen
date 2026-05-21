"""Search endpoint — Meilisearch if configured, Postgres ILIKE otherwise."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.api.v1 import _builders
from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.schemas.course import CourseListItem
from app.services.search import search_service

router = APIRouter()
log = get_logger(__name__)


@router.get("/courses", response_model=Page[CourseListItem])
async def search_courses(
    db: DBSession,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    subject: Annotated[str | None, Query(max_length=140)] = None,
    tag: Annotated[str | None, Query(max_length=80)] = None,
    difficulty: Annotated[str | None, Query(max_length=20)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Page[CourseListItem]:
    s = get_settings()

    if s.search_backend == "meilisearch":
        filters: list[str] = ['status = "published"']
        if subject:
            filters.append(f'subject_slug = "{subject}"')
        if tag:
            filters.append(f'tag_slugs = "{tag}"')
        if difficulty:
            filters.append(f'difficulty = "{difficulty}"')
        try:
            res = search_service.search(
                q, filters=filters, limit=page_size, offset=(page - 1) * page_size
            )
            ordered_ids = [str(hit["id"]) for hit in res.get("hits", [])]
            total = int(res.get("estimatedTotalHits", len(ordered_ids)))
        except Exception:  # noqa: BLE001 — fall back to Postgres if search is down
            log.exception("meilisearch_search_failed", q=q)
            return await _pg_search(db, q, subject, tag, difficulty, page, page_size)

        if not ordered_ids:
            return Page(items=[], total=total, page=page, page_size=page_size)
        rows = await courses_repo.get_courses_by_ids(db, ordered_ids)
        by_id = {c.id: c for c in rows}
        ordered = [by_id[i] for i in ordered_ids if i in by_id]
        stats = await courses_repo.stats_for_courses(db, [c.id for c in ordered])
        return Page(
            items=[_builders.list_item(c, stats.get(c.id, {})) for c in ordered],
            total=total,
            page=page,
            page_size=page_size,
        )

    return await _pg_search(db, q, subject, tag, difficulty, page, page_size)


async def _pg_search(
    db: AsyncSession,
    q: str,
    subject: str | None,
    tag: str | None,
    difficulty: str | None,
    page: int,
    page_size: int,
) -> Page[CourseListItem]:
    courses, total = await courses_repo.search_courses(
        db,
        q=q,
        subject_slug=subject,
        tag_slug=tag,
        difficulty=difficulty,
        page=page,
        page_size=page_size,
    )
    stats = await courses_repo.stats_for_courses(db, [c.id for c in courses])
    return Page(
        items=[_builders.list_item(c, stats.get(c.id, {})) for c in courses],
        total=total,
        page=page,
        page_size=page_size,
    )
