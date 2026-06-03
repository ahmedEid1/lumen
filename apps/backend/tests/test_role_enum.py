"""S1.1 — the ``Role`` enum widens to the Phase-A tolerance set.

During the two-role collapse the enum must accept all four values
``{student, instructor, user, admin}`` so no legacy ORM row or stale
request body crashes deserialization in the transition window (R-C5,
ADR-0025 §D1 Phase A). The narrow-to-``{user, admin}`` final cut is the
evidence-gated S1.13 / Phase D — NOT done here.
"""

from __future__ import annotations

import pytest

from app.models.user import Role


def test_role_enum_accepts_user_and_legacy():
    # All four strings resolve without ValueError (Phase-A tolerance).
    assert Role("user") is Role.user
    assert Role("admin") is Role.admin
    assert Role("student") is Role.student
    assert Role("instructor") is Role.instructor


def test_role_user_value_is_user():
    assert Role.user.value == "user"


def test_role_is_str_enum():
    # StrEnum: a Role compares/serialises as its string value, which the
    # JWT mint + Pydantic schemas rely on (`str(user.role)`).
    assert Role.user == "user"
    assert str(Role.user) == "user"


def test_unknown_role_still_raises():
    # Widening is bounded — a genuinely unknown value is still rejected so a
    # typo can't smuggle in a non-role.
    with pytest.raises(ValueError):
        Role("superuser")
