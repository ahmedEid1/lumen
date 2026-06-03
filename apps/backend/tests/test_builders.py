"""Unit tests for the shared response builders.

The builder must produce a stable public shape regardless of which router calls
it, so an isolated test guards against accidental drift.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.api.v1 import _builders
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    ModerationState,
    Module,
    Subject,
    Tag,
    Visibility,
)
from app.models.user import Role, User


def _user(**overrides) -> User:
    base = {
        "id": "u_1",
        "email": "i@lumen.test",
        "password_hash": "x",
        "full_name": "Tareq",
        "role": Role.instructor,
        "is_active": True,
        "failed_login_attempts": 0,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    user = User(**base)
    return user


def _subject() -> Subject:
    return Subject(
        id="s_1",
        title="Programming",
        slug="programming",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _course(
    *,
    with_tags: bool = True,
    status: CourseStatus = CourseStatus.published,
    visibility: Visibility = Visibility.public,
    moderation_state: ModerationState = ModerationState.approved,
) -> Course:
    # S2 / ADR-0026: ``CourseListItem`` / ``CourseDetail`` now serialize the
    # ``visibility`` + ``moderation_state`` axes, and the builder's
    # ``is_publicly_listed`` hint reads them off the row. This factory builds an
    # in-memory (uncommitted) ORM object, so the model's server defaults never
    # fire — we must set the axes explicitly. The default is the publicly-listed
    # shape (public + approved + published) these builder tests assume.
    owner = _user()
    subject = _subject()
    course = Course(
        id="c_1",
        owner_id=owner.id,
        subject_id=subject.id,
        title="FastAPI",
        slug="fastapi",
        overview="Build APIs",
        cover_url=None,
        difficulty=Difficulty.beginner,
        status=status,
        visibility=visibility,
        moderation_state=moderation_state,
        is_featured=True,
        published_at=datetime(2026, 5, 1, tzinfo=UTC),
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    course.owner = owner
    course.subject = subject
    course.tags = (
        [
            Tag(
                id="t_1",
                name="Python",
                slug="python",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]
        if with_tags
        else []
    )
    return course


def test_list_item_round_trip_with_stats() -> None:
    course = _course()
    item = _builders.list_item(
        course, {"modules_count": 4, "enrollments_count": 42, "avg_rating": 4.5}
    )
    assert item.id == "c_1"
    assert item.title == "FastAPI"
    assert item.slug == "fastapi"
    assert item.modules_count == 4
    assert item.enrollments_count == 42
    assert item.avg_rating == 4.5
    assert item.is_featured is True
    assert item.owner.id == "u_1"
    assert item.subject.slug == "programming"
    assert item.tags[0].slug == "python"


def test_list_item_defaults_when_stats_missing() -> None:
    item = _builders.list_item(_course(with_tags=False))
    assert item.modules_count == 0
    assert item.enrollments_count == 0
    assert item.avg_rating is None
    assert item.tags == []


def test_detail_passes_through_enrollment_flags() -> None:
    # The companion ``is_bookmarked`` assertion was dropped along with
    # the bookmark feature itself in rebuild Cut A7; the builder no
    # longer accepts an ``is_bookmarked=`` kwarg and ``CourseDetail``
    # no longer carries the field. We keep the enrollment + progress
    # pass-through case because those are still load-bearing.
    course = _course()
    module = Module(
        id="m_1",
        course_id="c_1",
        title="Intro",
        description="",
        order=0,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    module.lessons = []
    detail = _builders.detail(
        course,
        [module],
        {"modules_count": 1},
        is_enrolled=True,
        progress_pct=37.5,
    )
    assert detail.is_enrolled is True
    assert detail.progress_pct == 37.5
    assert detail.modules_count == 1
    assert len(detail.modules) == 1 and detail.modules[0].id == "m_1"


def test_detail_filters_deleted_lessons() -> None:
    from app.models.course import Lesson, LessonType

    course = _course()
    module = Module(
        id="m_1",
        course_id="c_1",
        title="M",
        description="",
        order=0,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    alive = Lesson(
        id="l_1",
        module_id="m_1",
        title="L",
        order=0,
        type=LessonType.text,
        duration_seconds=None,
        is_preview=False,
        data={"type": "text", "body_markdown": "x"},
        deleted_at=None,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    dead = Lesson(
        id="l_2",
        module_id="m_1",
        title="L",
        order=1,
        type=LessonType.text,
        duration_seconds=None,
        is_preview=False,
        data={"type": "text", "body_markdown": "x"},
        deleted_at=datetime(2026, 5, 2, tzinfo=UTC),
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    module.lessons = [alive, dead]

    detail = _builders.detail(course, [module])
    assert [lesson.id for lesson in detail.modules[0].lessons] == ["l_1"]
