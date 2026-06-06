"""S1.12 — the test fixtures default to the collapsed `user` role.

`make_user` / `auth_headers` default to ``Role.user`` post-collapse, but
explicit legacy overrides still resolve (the enum stays wide through Phase A)
so the legacy-tolerance tests can keep planting `instructor`/`student` rows.

DB-backed (uses `make_user`) — runs under `make test.api`.
"""

from __future__ import annotations

import pytest

from app.models.user import Role


@pytest.mark.asyncio
async def test_make_user_defaults_user_role(make_user):
    user = await make_user()
    assert user.role == Role.user


@pytest.mark.asyncio
async def test_make_user_explicit_legacy_override_still_works(make_user):
    # The S1.6 legacy-principal + 0031 migration tests rely on this.
    legacy = await make_user(email="explicit-instructor@lumen.test", role=Role.instructor)
    assert legacy.role == Role.instructor
    student = await make_user(email="explicit-student@lumen.test", role=Role.student)
    assert student.role == Role.student
