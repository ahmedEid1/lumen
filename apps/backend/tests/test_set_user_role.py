"""S6.6 — legacy /role write policy (FR-ADMIN-02).

The role-collapse settable set is ``{user, admin}``. S6.6 changes the legacy
``student``/``instructor`` write from a hard parse-time reject to a
*normalize-during-window-then-422-after-Phase-D* policy applied in the handler
(see ``test_admin.py::test_legacy_role_endpoint_normalizes_then_422`` for the
DB-backed path). The schema therefore now accepts ANY enum value at parse —
the policy decision moved out of the validator so a legacy value can be
*normalized* rather than rejected.

The settable/normalizable role *sets* are the unit-testable contract here.
"""

from __future__ import annotations

import pytest

from app.api.v1.admin import NORMALIZABLE_ROLES, SETTABLE_ROLES, UserRoleUpdate
from app.models.user import Role


def test_user_role_update_accepts_user():
    assert UserRoleUpdate(role="user").role == Role.user


def test_user_role_update_accepts_admin():
    assert UserRoleUpdate(role="admin").role == Role.admin


@pytest.mark.parametrize("legacy", ["student", "instructor"])
def test_user_role_update_parses_legacy_for_normalization(legacy):
    # S6.6: legacy values now parse (so the handler can normalize them); the
    # settable-vs-normalizable distinction is the policy boundary.
    parsed = UserRoleUpdate(role=legacy).role
    assert parsed in NORMALIZABLE_ROLES
    assert parsed not in SETTABLE_ROLES


def test_settable_and_normalizable_sets():
    assert frozenset({Role.user, Role.admin}) == SETTABLE_ROLES
    assert frozenset({Role.student, Role.instructor}) == NORMALIZABLE_ROLES
