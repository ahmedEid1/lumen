"""S1.8 — admin settable-role restriction (FR-RBAC-06, FR-ADMIN-07).

Once the collapse lands, the only roles an admin may *write* are
``{user, admin}``. Legacy ``student``/``instructor`` are *read-tolerant*
(the wide enum still loads them) but *write-forbidden* — a PATCH carrying a
legacy role is rejected with 422 ``user.invalid_role``.

The validator is on ``UserRoleUpdate`` (inline in admin.py), so it is
unit-testable without a DB. The end-to-end PATCH path is exercised DB-backed
in test_admin.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.admin import UserRoleUpdate
from app.models.user import Role


def test_user_role_update_accepts_user():
    assert UserRoleUpdate(role="user").role == Role.user


def test_user_role_update_accepts_admin():
    assert UserRoleUpdate(role="admin").role == Role.admin


@pytest.mark.parametrize("legacy", ["student", "instructor"])
def test_user_role_update_rejects_legacy(legacy):
    with pytest.raises(ValidationError):
        UserRoleUpdate(role=legacy)


def test_user_role_update_rejects_garbage():
    with pytest.raises(ValidationError):
        UserRoleUpdate(role="superuser")
