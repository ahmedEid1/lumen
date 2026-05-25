"""Search endpoint — Postgres tsvector + GIN (no external search service)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DBSession
from app.api.v1 import _builders
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.schemas.course import CourseListItem

router = APIRouter()


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
