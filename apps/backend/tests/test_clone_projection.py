"""S4.3 — Sanitized export projection (the clone security boundary).

The ``test_projection_field_whitelist`` + ``test_no_forbidden_attribute_paths``
tests are the most security-load-bearing tests in the clone stream
(CHARTER §3.4: "whitelist projection makes leakage structurally impossible").
``test_field_set_tripwire`` is the regression tripwire: adding ANY new
``Course``/``Module``/``Lesson`` column makes it fail until the column is
explicitly classified copy-or-exclude in ``clone_projection``.

Pure, in-memory — no DB, no I/O.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.models.course import Course, Difficulty, Lesson, LessonType, Module
from app.services.clone_projection import (
    COURSE_COPY_FIELDS,
    COURSE_EXCLUDE_FIELDS,
    LESSON_COPY_FIELDS,
    LESSON_EXCLUDE_FIELDS,
    MODULE_COPY_FIELDS,
    MODULE_EXCLUDE_FIELDS,
    CloneSourceTooLargeError,
    CourseExport,
    CourseExportLesson,
    CourseExportModule,
    build_export_projection,
)

# --------------------------------------------------------------------------
# In-memory fixtures (no DB)
# --------------------------------------------------------------------------


def _lesson(
    *,
    title: str,
    order: int,
    ltype: LessonType = LessonType.text,
    is_preview: bool = False,
    deleted: bool = False,
    data: dict | None = None,
    module_id: str = "m1",
) -> Lesson:
    le = Lesson()
    le.id = f"lesson_{title}"
    le.module_id = module_id
    le.title = title
    le.order = order
    le.type = ltype
    le.duration_seconds = 60
    le.is_preview = is_preview
    le.data = data if data is not None else {"type": "text", "body_markdown": title}
    le.deleted_at = "2026-01-01T00:00:00Z" if deleted else None
    return le


def _module(*, mid: str, title: str, order: int) -> Module:
    mo = Module()
    mo.id = mid
    mo.course_id = "src"
    mo.title = title
    mo.description = f"{title} desc"
    mo.order = order
    return mo


def _course() -> Course:
    c = Course()
    c.id = "src"
    c.owner_id = "owner1"
    c.subject_id = "subj1"
    c.title = "Source Course"
    c.slug = "source-course"
    c.overview = "An overview"
    c.learning_outcomes = ["a", "b"]
    c.cover_url = "https://x/cover.png"
    c.difficulty = Difficulty.intermediate
    return c


def _build(course, modules, lessons, *, max_lessons=500, max_data_bytes=50_000_000):
    return build_export_projection(
        course,
        modules,
        lessons,
        max_lessons=max_lessons,
        max_data_bytes=max_data_bytes,
    )


# --------------------------------------------------------------------------
# Field whitelist + structural absence
# --------------------------------------------------------------------------


def test_projection_field_whitelist() -> None:
    """The CourseExport dataclass exposes EXACTLY the whitelisted fields."""
    course_fields = {f.name for f in dataclasses.fields(CourseExport)}
    assert course_fields == {
        "title",
        "overview",
        "difficulty",
        "learning_outcomes",
        "subject_id",
        "tag_ids",
        "cover_url",
        "modules",
        "lessons_copied",
        "modules_copied",
        "modules_dropped",
    }

    module_fields = {f.name for f in dataclasses.fields(CourseExportModule)}
    assert module_fields == {"title", "description", "order", "lessons"}

    lesson_fields = {f.name for f in dataclasses.fields(CourseExportLesson)}
    assert lesson_fields == {
        "title",
        "type",
        "duration_seconds",
        "is_preview",
        "order",
        "data",
    }
    # Forbidden columns must NOT be reachable on the lesson export.
    for forbidden in ("id", "deleted_at", "published_at", "owner_id", "module_id"):
        assert forbidden not in lesson_fields


def test_no_forbidden_attribute_paths() -> None:
    """No attribute path from the export carries forbidden source state."""
    course = _course()
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title="L1", order=0, module_id="m1")]
    export = _build(course, modules, lessons)

    # The export carries no relationship handles back to the ORM graph.
    for forbidden in (
        "reviews",
        "enrollments",
        "lesson_progress",
        "lesson_chunks",
        "origin_course_id",
        "origin_owner_id",
        "is_featured",
        "published_at",
        "deleted_at",
        "slug",
        "owner_id",
        "moderation_state",
        "search_vector",
    ):
        assert not hasattr(export, forbidden)
    le = export.modules[0].lessons[0]
    for forbidden in ("id", "deleted_at", "module_id", "progress"):
        assert not hasattr(le, forbidden)


def test_field_set_tripwire() -> None:
    """REGRESSION TRIPWIRE: every Course/Module/Lesson column is classified.

    The union of the explicit COPY and EXCLUDE classification sets must equal
    the model's full column set. A new column added to any of the three models
    fails this test until a human classifies it copy-or-exclude in
    ``clone_projection`` — so a new column can NEVER silently leak across the
    clone ownership boundary.
    """
    course_cols = set(Course.__table__.columns.keys())
    assert course_cols == COURSE_COPY_FIELDS | COURSE_EXCLUDE_FIELDS, (
        "Unclassified Course column(s): "
        f"{course_cols - (COURSE_COPY_FIELDS | COURSE_EXCLUDE_FIELDS)}"
    )
    assert not (COURSE_COPY_FIELDS & COURSE_EXCLUDE_FIELDS), "a Course column is in both sets"

    module_cols = set(Module.__table__.columns.keys())
    assert module_cols == MODULE_COPY_FIELDS | MODULE_EXCLUDE_FIELDS, (
        "Unclassified Module column(s): "
        f"{module_cols - (MODULE_COPY_FIELDS | MODULE_EXCLUDE_FIELDS)}"
    )
    assert not (MODULE_COPY_FIELDS & MODULE_EXCLUDE_FIELDS), "a Module column is in both sets"

    lesson_cols = set(Lesson.__table__.columns.keys())
    assert lesson_cols == LESSON_COPY_FIELDS | LESSON_EXCLUDE_FIELDS, (
        "Unclassified Lesson column(s): "
        f"{lesson_cols - (LESSON_COPY_FIELDS | LESSON_EXCLUDE_FIELDS)}"
    )
    assert not (LESSON_COPY_FIELDS & LESSON_EXCLUDE_FIELDS), "a Lesson column is in both sets"


def test_provenance_columns_are_excluded() -> None:
    """The source's own provenance must never be copied (no lineage smuggling)."""
    for col in (
        "origin_course_id",
        "origin_owner_id",
        "root_origin_course_id",
        "origin_title_snapshot",
        "origin_owner_name_snapshot",
        "cloned_at",
    ):
        assert col in COURSE_EXCLUDE_FIELDS


# --------------------------------------------------------------------------
# Behavior
# --------------------------------------------------------------------------


def test_drops_empty_modules() -> None:
    course = _course()
    modules = [
        _module(mid="m1", title="Live", order=0),
        _module(mid="m2", title="Empty", order=1),
    ]
    lessons = [
        _lesson(title="L1", order=0, module_id="m1"),
        _lesson(title="Dead", order=0, module_id="m2", deleted=True),
    ]
    export = _build(course, modules, lessons)
    assert [m.title for m in export.modules] == ["Live"]
    assert export.modules_dropped == 1
    assert export.modules_copied == 1


def test_soft_deleted_lessons_excluded() -> None:
    course = _course()
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [
        _lesson(title="Live", order=0, module_id="m1"),
        _lesson(title="Dead", order=1, module_id="m1", deleted=True),
    ]
    export = _build(course, modules, lessons)
    titles = [le.title for le in export.modules[0].lessons]
    assert titles == ["Live"]
    assert export.lessons_copied == 1


def test_is_preview_forced_false() -> None:
    course = _course()
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title="Preview", order=0, module_id="m1", is_preview=True)]
    export = _build(course, modules, lessons)
    assert export.modules[0].lessons[0].is_preview is False


def test_dense_zero_based_orders() -> None:
    course = _course()
    modules = [
        _module(mid="m1", title="M-a", order=2),
        _module(mid="m2", title="M-b", order=5),
        _module(mid="m3", title="M-c", order=9),
    ]
    lessons = [
        _lesson(title="la1", order=2, module_id="m1"),
        _lesson(title="la2", order=5, module_id="m1"),
        _lesson(title="la3", order=9, module_id="m1"),
        _lesson(title="lb1", order=4, module_id="m2"),
        _lesson(title="lc1", order=7, module_id="m3"),
    ]
    export = _build(course, modules, lessons)
    # Modules re-keyed dense 0-based, display order preserved.
    assert [m.order for m in export.modules] == [0, 1, 2]
    assert [m.title for m in export.modules] == ["M-a", "M-b", "M-c"]
    # Lessons in the first module dense 0-based, display order preserved.
    first = export.modules[0]
    assert [le.order for le in first.lessons] == [0, 1, 2]
    assert [le.title for le in first.lessons] == ["la1", "la2", "la3"]


def test_quiz_data_verbatim_deepcopy() -> None:
    quiz = {
        "type": "quiz",
        "pass_score": 70,
        "questions": [
            {
                "id": "q1",
                "prompt": "2+2?",
                "kind": "single",
                "choices": [{"id": "c1", "text": "4"}, {"id": "c2", "text": "5"}],
                "answer_keys": ["c1"],
            }
        ],
    }
    course = _course()
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title="Quiz", order=0, ltype=LessonType.quiz, module_id="m1", data=quiz)]
    export = _build(course, modules, lessons)
    exported = export.modules[0].lessons[0].data
    # Verbatim, ids preserved.
    assert exported == quiz
    assert exported["questions"][0]["answer_keys"] == ["c1"]
    # Deep copy: mutating the export does not mutate the source.
    exported["questions"][0]["answer_keys"].append("c2")
    assert quiz["questions"][0]["answer_keys"] == ["c1"]


def test_counters() -> None:
    course = _course()
    modules = [
        _module(mid="m1", title="Live1", order=0),
        _module(mid="m2", title="Live2", order=1),
        _module(mid="m3", title="Empty", order=2),
    ]
    lessons = [
        _lesson(title="l1", order=0, module_id="m1"),
        _lesson(title="l2", order=1, module_id="m1"),
        _lesson(title="l3", order=0, module_id="m2"),
        _lesson(title="dead", order=0, module_id="m3", deleted=True),
    ]
    export = _build(course, modules, lessons)
    assert export.lessons_copied == 3
    assert export.modules_copied == 2
    assert export.modules_dropped == 1


def test_size_ceiling_too_many_lessons() -> None:
    course = _course()
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title=f"l{i}", order=i, module_id="m1") for i in range(5)]
    with pytest.raises(CloneSourceTooLargeError):
        _build(course, modules, lessons, max_lessons=4)


def test_size_ceiling_data_bytes() -> None:
    course = _course()
    big = {"type": "text", "body_markdown": "x" * 1000}
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title="l", order=0, module_id="m1", data=big)]
    with pytest.raises(CloneSourceTooLargeError):
        _build(course, modules, lessons, max_data_bytes=100)


def test_tag_ids_only() -> None:
    """Tags are platform-shared: project tag IDS only, not Tag rows."""
    from app.models.course import Tag

    course = _course()
    t1, t2 = Tag(), Tag()
    t1.id, t1.name, t1.slug = "tag1", "Python", "python"
    t2.id, t2.name, t2.slug = "tag2", "Async", "async"
    course.tags = [t1, t2]
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title="l", order=0, module_id="m1")]
    export = _build(course, modules, lessons)
    assert export.tag_ids == ["tag1", "tag2"]


def test_learning_outcomes_list_copied_not_shared() -> None:
    course = _course()
    modules = [_module(mid="m1", title="Mod", order=0)]
    lessons = [_lesson(title="l", order=0, module_id="m1")]
    export = _build(course, modules, lessons)
    assert export.learning_outcomes == ["a", "b"]
    export.learning_outcomes.append("c")
    assert course.learning_outcomes == ["a", "b"]
