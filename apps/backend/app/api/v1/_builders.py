"""Response builders shared across course-facing endpoints.

Centralizes the otherwise-duplicated ``CourseListItem`` and ``CourseDetail``
construction so the public shape is enforced in one place.
"""

from __future__ import annotations

from typing import Any

from app.models.course import Course, Module
from app.schemas.course import (
    CourseDetail,
    CourseListItem,
    LessonOut,
    ModuleOut,
    SubjectOut,
    TagOut,
)
from app.schemas.user import UserPublic


def list_item(course: Course, stats: dict[str, Any] | None = None) -> CourseListItem:
    """Build a public-shape ``CourseListItem`` from an ORM Course + stats row."""
    s = stats or {}
    return CourseListItem(
        id=course.id,
        title=course.title,
        slug=course.slug,
        overview=course.overview,
        difficulty=course.difficulty,
        cover_url=course.cover_url,
        status=course.status,
        is_featured=course.is_featured,
        published_at=course.published_at,
        created_at=course.created_at,
        owner=UserPublic.model_validate(course.owner),
        subject=SubjectOut.model_validate(course.subject),
        tags=[TagOut.model_validate(t) for t in course.tags],
        modules_count=int(s.get("modules_count", 0) or 0),
        enrollments_count=int(s.get("enrollments_count", 0) or 0),
        avg_rating=s.get("avg_rating"),
    )


def _lesson_out(lesson: Any, completed_ids: set[str]) -> LessonOut:
    base = LessonOut.model_validate(lesson)
    if lesson.id in completed_ids:
        base = base.model_copy(update={"completed": True})
    return base


def detail(
    course: Course,
    modules: list[Module],
    stats: dict[str, Any] | None = None,
    *,
    is_enrolled: bool = False,
    is_bookmarked: bool = False,
    progress_pct: float = 0.0,
    completed_lesson_ids: set[str] | None = None,
) -> CourseDetail:
    base = list_item(course, stats)
    done = completed_lesson_ids or set()
    return CourseDetail(
        **base.model_dump(),
        modules=[
            ModuleOut(
                id=m.id,
                title=m.title,
                description=m.description,
                order=m.order,
                lessons=[
                    _lesson_out(lesson, done)
                    for lesson in m.lessons
                    if getattr(lesson, "deleted_at", None) is None
                ],
            )
            for m in modules
        ],
        is_enrolled=is_enrolled,
        is_bookmarked=is_bookmarked,
        progress_pct=progress_pct,
        learning_outcomes=list(course.learning_outcomes or []),
    )
