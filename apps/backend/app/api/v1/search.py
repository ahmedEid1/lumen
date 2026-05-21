"""Search endpoint — Meilisearch if configured, Postgres ILIKE otherwise."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DBSession
from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.schemas.course import CourseListItem, SubjectOut, TagOut
from app.schemas.user import UserPublic
from app.services.search import search_service

router = APIRouter()
log = get_logger(__name__)


def _to_list_item(c: Any, stats_for_id: dict[str, Any]) -> CourseListItem:
    return CourseListItem(
        id=c.id,
        title=c.title,
        slug=c.slug,
        overview=c.overview,
        difficulty=c.difficulty,
        cover_url=c.cover_url,
        status=c.status,
        is_featured=c.is_featured,
        published_at=c.published_at,
        created_at=c.created_at,
        owner=UserPublic.model_validate(c.owner),
        subject=SubjectOut.model_validate(c.subject),
        tags=[TagOut.model_validate(t) for t in c.tags],
        modules_count=int(stats_for_id.get("modules_count", 0) or 0),
        enrollments_count=int(stats_for_id.get("enrollments_count", 0) or 0),
        avg_rating=stats_for_id.get("avg_rating"),
    )


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
            items=[_to_list_item(c, stats.get(c.id, {})) for c in ordered],
            total=total,
            page=page,
            page_size=page_size,
        )

    return await _pg_search(db, q, subject, tag, difficulty, page, page_size)


async def _pg_search(
    db: Any,
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
        items=[_to_list_item(c, stats.get(c.id, {})) for c in courses],
        total=total,
        page=page,
        page_size=page_size,
    )
