"""Response builders shared across course-facing endpoints.

Centralizes the otherwise-duplicated ``CourseListItem`` and ``CourseDetail``
construction so the public shape is enforced in one place.
"""

from __future__ import annotations

from typing import Any

from app.models.course import Course, Module
from app.models.user import User
from app.schemas.course import (
    CourseDetail,
    CourseListItem,
    CourseOrigin,
    LessonOut,
    ModuleOut,
    SubjectOut,
    TagOut,
    build_course_origin,
)
from app.schemas.user import UserPublic
from app.services import visibility as visibility_service


def _viewer_is_owner_or_admin(course: Course, viewer: User | None) -> bool:
    if viewer is None:
        return False
    return viewer.is_admin() or course.owner_id == viewer.id


def list_item(
    course: Course,
    stats: dict[str, Any] | None = None,
    *,
    viewer: User | None = None,
    origin: CourseOrigin | None = None,
) -> CourseListItem:
    """Build a ``CourseListItem`` from an ORM Course + stats row.

    ``visibility`` is always exposed; ``moderation_state`` is REDACTED to
    ``None`` for non-owner/non-admin viewers (FR-VIS-21 — a listed course shows
    nothing internal).

    ``origin`` is the clone provenance (ADR-0028 / FR-CLONE-09/10): when the
    caller passes a pre-resolved :class:`CourseOrigin` (the S4.8 read-time
    resolver — ``origin_available`` + deleted-owner anonymization), it is used
    verbatim; otherwise it falls back to a snapshot-only projection (no source
    link, raw owner-name snapshot). ``is_clone`` is the studio "Cloned" badge
    flag = ``origin_course_id is not None``.
    """
    s = stats or {}
    privileged = _viewer_is_owner_or_admin(course, viewer)
    resolved_origin = origin if origin is not None else build_course_origin(course)
    return CourseListItem(
        id=course.id,
        title=course.title,
        slug=course.slug,
        overview=course.overview,
        difficulty=course.difficulty,
        cover_url=course.cover_url,
        status=course.status,
        visibility=course.visibility,
        moderation_state=course.moderation_state if privileged else None,
        is_featured=course.is_featured,
        published_at=course.published_at,
        created_at=course.created_at,
        owner=UserPublic.model_validate(course.owner),
        subject=SubjectOut.model_validate(course.subject),
        tags=[TagOut.model_validate(t) for t in course.tags],
        modules_count=int(s.get("modules_count", 0) or 0),
        enrollments_count=int(s.get("enrollments_count", 0) or 0),
        avg_rating=s.get("avg_rating"),
        origin=resolved_origin,
        is_clone=getattr(course, "origin_course_id", None) is not None,
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
    progress_pct: float = 0.0,
    completed_lesson_ids: set[str] | None = None,
    viewer: User | None = None,
    origin: CourseOrigin | None = None,
) -> CourseDetail:
    base = list_item(course, stats, viewer=viewer, origin=origin)
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
        progress_pct=progress_pct,
        is_publicly_listed=visibility_service.is_publicly_listed(course),
        # Owner-only capability hint (FR-VIS-21): None for non-owner viewers.
        can_publish_public=(
            visibility_service.can_publish_public(viewer)
            if (viewer is not None and course.owner_id == viewer.id)
            else None
        ),
        learning_outcomes=list(course.learning_outcomes or []),
    )
