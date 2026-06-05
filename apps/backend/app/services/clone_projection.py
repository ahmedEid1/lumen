"""Sanitized export projection — the clone security boundary (ADR-0028 §1).

This module is the structural answer to CHARTER §3.4: a clone is a **sanitized
export projection of a published-public snapshot**, never an ORM walk that drags
hidden/private/soft-deleted state across an ownership boundary. The projection
copies ONLY an explicit whitelist into frozen dataclasses; anything not on the
whitelist cannot cross — there is no attribute path from the export back to
``reviews``/``enrollments``/``lesson_progress``/``lesson_chunks``/``origin_*``
or to the source's owner/slug/visibility/moderation state.

The classification sets (``*_COPY_FIELDS`` / ``*_EXCLUDE_FIELDS``) are a frozen
whitelist tripwire: ``tests/test_clone_projection.py::test_field_set_tripwire``
asserts their union equals the model's full column set, so a new
``Course``/``Module``/``Lesson`` column fails the test until a human explicitly
classifies it copy-or-exclude — a new column can never silently leak (FR-CLONE-04
/05/06/07, R-M1, R-M4).

Pure: no DB, no I/O. The caller loads the snapshot (with modules + lessons) in a
single read transaction and passes the rows in; this builder filters
soft-deleted lessons, drops empty modules, re-keys to dense 0-based orders,
forces ``is_preview=False``, deep-copies quiz ``data`` verbatim, and enforces the
source-size ceiling (FR-CLONE-18).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.course import Course, Lesson, Module


# ---------------------------------------------------------------------------
# Whitelist classification — the frozen tripwire (see module docstring).
#
# COPY = carried into the export (the whitelist). EXCLUDE = deliberately dropped.
# Their union MUST equal each model's full column set (test_field_set_tripwire),
# so a NEW column is a hard test failure until classified — no silent leakage.
# ---------------------------------------------------------------------------

#: Course columns copied into the export. ``tag_ids`` is sourced from the
#: ``tags`` relationship (platform-shared Tag rows, associated by id), not a
#: column, so it is not in this column-keyed set.
COURSE_COPY_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "overview",
        "difficulty",
        "learning_outcomes",
        "subject_id",
        "cover_url",
    }
)

#: Course columns explicitly NOT copied. Identity/lifecycle/ownership/moderation
#: state and the source's OWN provenance (no lineage smuggling) all stay behind.
COURSE_EXCLUDE_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "owner_id",
        "slug",
        "status",
        "visibility",
        "moderation_state",
        "published_at",
        # Self-serve build completion marker (migration 0052) — a build-lifecycle
        # timestamp of the SOURCE; a clone is a fresh course, never a finished
        # build of the source, so it is deliberately dropped.
        "build_completed_at",
        "is_featured",
        "quarantined",
        "deleted_at",
        "review_flagged_at",
        "search_vector",
        "created_at",
        "updated_at",
        # Source provenance — never copied (clone provenance is server-written
        # fresh in clone_course; copying these would forge lineage).
        "origin_course_id",
        "origin_owner_id",
        "root_origin_course_id",
        "origin_title_snapshot",
        "origin_owner_name_snapshot",
        "cloned_at",
    }
)

MODULE_COPY_FIELDS: frozenset[str] = frozenset({"title", "description", "order"})
MODULE_EXCLUDE_FIELDS: frozenset[str] = frozenset({"id", "course_id", "created_at", "updated_at"})

#: Lesson columns copied. ``is_preview`` is copied structurally but FORCED to
#: False at materialization (R-M4 / FR-CLONE-04) — it is on the whitelist so the
#: tripwire accounts for it, but its value is never the source's.
LESSON_COPY_FIELDS: frozenset[str] = frozenset(
    {"title", "type", "duration_seconds", "is_preview", "order", "data"}
)
LESSON_EXCLUDE_FIELDS: frozenset[str] = frozenset(
    {"id", "module_id", "deleted_at", "created_at", "updated_at"}
)


class CloneSourceTooLargeError(Exception):
    """The source exceeds the clone size ceiling (FR-CLONE-18).

    Raised by the pure projection so the call path (S4.6/S4.7) can map it to the
    ``clone.source_too_large`` 413/422 envelope. Self-contained here so the
    projection has no dependency on the HTTP error module.
    """

    def __init__(self, message: str, *, lessons: int | None = None, data_bytes: int | None = None):
        super().__init__(message)
        self.lessons = lessons
        self.data_bytes = data_bytes


# ---------------------------------------------------------------------------
# Frozen export DTOs — the whitelist boundary made structural.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CourseExportLesson:
    title: str
    type: str
    duration_seconds: int | None
    is_preview: bool  # always False (R-M4) — see build_export_projection
    order: int  # dense 0-based per module
    data: dict  # deep-copied verbatim (quiz payloads incl. ids preserved)


@dataclass(frozen=True, slots=True)
class CourseExportModule:
    title: str
    description: str
    order: int  # dense 0-based
    lessons: list[CourseExportLesson]


@dataclass(frozen=True, slots=True)
class CourseExport:
    title: str
    overview: str
    difficulty: str
    learning_outcomes: list[str]
    subject_id: str
    tag_ids: list[str]
    cover_url: str | None
    modules: list[CourseExportModule]
    # Audit counters (FR-CLONE-19).
    lessons_copied: int
    modules_copied: int
    modules_dropped: int


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_export_projection(
    course: Course,
    modules: Iterable[Module],
    lessons: Iterable[Lesson],
    *,
    max_lessons: int,
    max_data_bytes: int,
) -> CourseExport:
    """Build the sanitized export projection (pure, no DB/IO).

    ``modules``/``lessons`` are the rows loaded in the snapshot transaction. The
    relationship loader returns soft-deleted lessons, so we filter
    ``deleted_at IS NULL`` here (mirroring ``courses.py``'s ``update_module``).
    Modules with zero live lessons are dropped (FR-CLONE-05). Orders are re-keyed
    to a dense gap-free 0-based sequence in source display order — satisfying
    ``uq_modules_course_order``/``uq_lessons_module_order`` on first INSERT, no
    two-phase reorder. ``is_preview`` is forced False; ``data`` is deep-copied
    verbatim. Raises :class:`CloneSourceTooLargeError` past the size ceiling.
    """
    lessons_by_module: dict[str, list[Lesson]] = {}
    for le in lessons:
        if le.deleted_at is not None:
            continue  # explicit deleted_at IS NULL filter (FR-CLONE-05)
        lessons_by_module.setdefault(le.module_id, []).append(le)

    # Size ceiling — live lesson count (FR-CLONE-18).
    live_lesson_count = sum(len(v) for v in lessons_by_module.values())
    if live_lesson_count > max_lessons:
        raise CloneSourceTooLargeError(
            f"Source has {live_lesson_count} live lessons (>{max_lessons})",
            lessons=live_lesson_count,
        )

    export_modules: list[CourseExportModule] = []
    modules_dropped = 0
    lessons_copied = 0
    total_data_bytes = 0

    # Source display order for modules; dense re-key on the surviving ones.
    ordered_modules: Sequence[Module] = sorted(modules, key=lambda m: m.order)
    next_module_order = 0
    for mod in ordered_modules:
        live = sorted(lessons_by_module.get(mod.id, []), key=lambda le: le.order)
        if not live:
            modules_dropped += 1
            continue  # empty module dropped (FR-CLONE-05)

        export_lessons: list[CourseExportLesson] = []
        for lesson_order, le in enumerate(live):
            data_copy = copy.deepcopy(le.data) if le.data is not None else {}
            # Byte ceiling over the projected data payloads (FR-CLONE-18).
            total_data_bytes += len(
                json.dumps(data_copy, separators=(",", ":"), default=str).encode("utf-8")
            )
            if total_data_bytes > max_data_bytes:
                raise CloneSourceTooLargeError(
                    f"Projected lesson data exceeds {max_data_bytes} bytes",
                    data_bytes=total_data_bytes,
                )
            export_lessons.append(
                CourseExportLesson(
                    title=le.title,
                    type=str(le.type),
                    duration_seconds=le.duration_seconds,
                    is_preview=False,  # R-M4 / FR-CLONE-04 — never the source's value
                    order=lesson_order,  # dense 0-based
                    data=data_copy,
                )
            )
            lessons_copied += 1

        export_modules.append(
            CourseExportModule(
                title=mod.title,
                description=mod.description,
                order=next_module_order,  # dense 0-based
                lessons=export_lessons,
            )
        )
        next_module_order += 1

    tag_ids = [t.id for t in getattr(course, "tags", []) or []]

    return CourseExport(
        title=course.title,
        overview=course.overview,
        difficulty=str(course.difficulty),
        learning_outcomes=list(course.learning_outcomes or []),
        subject_id=course.subject_id,
        tag_ids=tag_ids,
        cover_url=course.cover_url,
        modules=export_modules,
        lessons_copied=lessons_copied,
        modules_copied=len(export_modules),
        modules_dropped=modules_dropped,
    )
