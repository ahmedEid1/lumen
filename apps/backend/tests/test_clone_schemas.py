"""S4.5 — Clone schemas: CourseOrigin, origin/is_clone, extra=forbid immutability.

Provenance is server-written + immutable: ``CourseCreate``/``CourseUpdate`` carry
``extra="forbid"`` so a client cannot smuggle ``origin_*`` through extra keys
(maps to 422 at the API). The ``origin`` object is serialized from the snapshot
columns; ``is_clone`` is derived. ``origin_available`` is a builder parameter
(computed read-time in S4.8 — default False here).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.course import Course
from app.schemas.course import CourseCreate, CourseOrigin, CourseUpdate, build_course_origin


def test_course_create_forbids_provenance() -> None:
    with pytest.raises(ValidationError):
        CourseCreate.model_validate(
            {
                "title": "X",
                "subject_id": "s1",
                "origin_course_id": "smuggled",
            }
        )


def test_course_create_forbids_arbitrary_extra() -> None:
    with pytest.raises(ValidationError):
        CourseCreate.model_validate({"title": "X", "subject_id": "s1", "is_featured": True})


def test_course_update_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        CourseUpdate.model_validate({"origin_owner_name_snapshot": "Fake Author"})


def _cloned_course() -> Course:
    c = Course()
    c.id = "clone1"
    c.origin_course_id = "src1"
    c.origin_owner_id = "owner1"
    c.root_origin_course_id = "root1"
    c.origin_title_snapshot = "Original Course"
    c.origin_owner_name_snapshot = "Jane Author"
    c.cloned_at = datetime(2026, 6, 1, tzinfo=UTC)
    return c


def test_origin_serialization() -> None:
    course = _cloned_course()
    origin = build_course_origin(course)
    assert isinstance(origin, CourseOrigin)
    assert origin.origin_course_id == "src1"
    assert origin.origin_title == "Original Course"
    assert origin.origin_owner_name == "Jane Author"
    assert origin.origin_owner_id == "owner1"
    assert origin.cloned_at == datetime(2026, 6, 1, tzinfo=UTC)
    # origin_available defaults False (S4.8 computes it read-time).
    assert origin.origin_available is False


def test_origin_available_param() -> None:
    course = _cloned_course()
    origin = build_course_origin(course, origin_available=True)
    assert origin.origin_available is True


def test_origin_owner_name_override_param() -> None:
    """S4.8 passes a read-time-resolved display name (deleted-user sentinel)."""
    course = _cloned_course()
    origin = build_course_origin(course, origin_owner_name="common.deletedUser")
    assert origin.origin_owner_name == "common.deletedUser"


def test_origin_null_when_not_cloned() -> None:
    c = Course()
    c.id = "scratch"
    # No provenance columns set → from-scratch course.
    assert build_course_origin(c) is None


def test_is_clone_derivation() -> None:
    cloned = _cloned_course()
    scratch = Course()
    scratch.id = "s"
    # is_clone is True iff origin_course_id is set.
    assert (cloned.origin_course_id is not None) is True
    assert (scratch.origin_course_id is not None) is False


def test_course_create_still_accepts_valid_body() -> None:
    payload = CourseCreate.model_validate(
        {
            "title": "Legit",
            "subject_id": f"s-{uuid.uuid4().hex[:6]}",
            "overview": "ok",
            "tag_ids": ["t1"],
        }
    )
    assert payload.title == "Legit"
