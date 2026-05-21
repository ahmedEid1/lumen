"""Catalog endpoints: subjects, tags, and the searchable course list."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DBSession, OptionalUser
from app.api.v1 import _builders
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.schemas.course import CourseListItem, SubjectOut, TagOut

router = APIRouter()


@router.get("/subjects", response_model=list[SubjectOut])
async def list_subjects(db: DBSession) -> list[SubjectOut]:
    rows = await courses_repo.list_subjects(db)
    return [SubjectOut(id=s.id, title=s.title, slug=s.slug, total_courses=n) for s, n in rows]


@router.get("/tags", response_model=list[TagOut])
async def list_tags(db: DBSession) -> list[TagOut]:
    rows = await courses_repo.list_tags(db)
    return [TagOut.model_validate(t) for t in rows]


@router.get("/courses", response_model=Page[CourseListItem])
async def list_courses(
    db: DBSession,
    _: OptionalUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    subject: Annotated[str | None, Query(max_length=140)] = None,
    tag: Annotated[str | None, Query(max_length=80)] = None,
    difficulty: Annotated[str | None, Query(max_length=20)] = None,
    sort: Annotated[str, Query(max_length=40)] = "-created_at",
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[CourseListItem]:
    courses, total = await courses_repo.search_courses(
        db,
        q=q,
        subject_slug=subject,
        tag_slug=tag,
        difficulty=difficulty,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    stats = await courses_repo.stats_for_courses(db, [c.id for c in courses])
    items = [_builders.list_item(c, stats.get(c.id, {})) for c in courses]
    return Page(items=items, total=total, page=page, page_size=page_size)
