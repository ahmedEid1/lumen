"""Course bookmarks (favorites) — per-user."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.api.v1 import _builders
from app.core.errors import NotFoundError
from app.models.bookmark import Bookmark
from app.models.course import Course
from app.repositories import courses as courses_repo
from app.schemas.common import OkResponse
from app.schemas.course import CourseListItem

router = APIRouter()


@router.get("", response_model=list[CourseListItem])
async def list_my_bookmarks(user: CurrentUser, db: DBSession) -> list[CourseListItem]:
    res = await db.execute(
        select(Bookmark)
        .options(
            selectinload(Bookmark.course).selectinload(Course.subject),
            selectinload(Bookmark.course).selectinload(Course.owner),
            selectinload(Bookmark.course).selectinload(Course.tags),
        )
        .where(Bookmark.user_id == user.id)
        .order_by(Bookmark.created_at.desc())
    )
    bookmarks = list(res.scalars().unique().all())
    stats = await courses_repo.stats_for_courses(db, [b.course_id for b in bookmarks])
    return [
        _builders.list_item(b.course, stats.get(b.course_id, {}))
        for b in bookmarks
        if b.course.deleted_at is None
    ]


@router.put("/{course_id}", response_model=OkResponse, status_code=status.HTTP_201_CREATED)
async def add_bookmark(course_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    course = await courses_repo.get_course(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course.not_found")
    existing = (
        await db.execute(
            select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.course_id == course.id)
        )
    ).scalar_one_or_none()
    if existing:
        return OkResponse()
    db.add(Bookmark(user_id=user.id, course_id=course.id))
    await db.flush()
    return OkResponse()


@router.delete("/{course_id}", response_model=OkResponse)
async def remove_bookmark(course_id: str, user: CurrentUser, db: DBSession) -> OkResponse:
    existing = (
        await db.execute(
            select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.course_id == course_id)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
    return OkResponse()
