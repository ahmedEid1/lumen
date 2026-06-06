"""S1.6 — MCP principal & enforcement reconcile (ADR-0025 §D5, FR-RBAC-07/08).

The MCP write gate moves off the `is_instructor` role check to the capability
`can_author`, while keeping legacy `instructor` principals working through the
collapse window and keeping `ingest_url_to_draft` admin-only (DR-M12).

These are pure-unit tests: a `Principal` is built over an in-memory `User`
(no DB) and `_enforce_auth` / `_require_author` are exercised directly. The
DB-backed happy paths live in test_mcp_tools.py.
"""

from __future__ import annotations

import pytest

from app.core.errors import ForbiddenError
from app.mcp import server as mcp_server
from app.mcp import tools as mcp_tools
from app.mcp.principal import Principal
from app.models.user import Role, User


def _principal(role: Role, *, is_active: bool = True, scopes: list[str] | None = None) -> Principal:
    user = User(
        email="p@lumen.test",
        password_hash="x",
        full_name="P",
        role=role,
        is_active=is_active,
    )
    return Principal(
        user_id="user_1",
        role=role,
        scopes=list(scopes if scopes is not None else ["*"]),
        client_id="client_1",
        user=user,
    )


def _spec(name: str):
    return next(s for s in mcp_tools.TOOL_SPECS if s.name == name)


# ---------- Principal capability properties ----------


def test_principal_can_author_active_user():
    assert _principal(Role.user).can_author is True


def test_principal_can_author_legacy_instructor():
    # Phase-A tolerance: a legacy `instructor` principal still authors.
    assert _principal(Role.instructor).can_author is True


def test_principal_can_author_admin():
    assert _principal(Role.admin).can_author is True


def test_principal_can_author_suspended_false():
    assert _principal(Role.user, is_active=False).can_author is False


def test_principal_can_use_mcp_authoring_uses_flag():
    from app.core.config import get_settings

    settings = get_settings()
    p = _principal(Role.user)
    # mcp_authoring_enabled defaults True.
    assert p.can_use_mcp_authoring(settings) is True
    assert _principal(Role.user, is_active=False).can_use_mcp_authoring(settings) is False


def test_principal_can_ingest_url_admin_only_and_flag_off_by_default():
    from app.core.config import get_settings

    settings = get_settings()
    # Default: ingest_url_enabled=False → even admin is False.
    assert _principal(Role.admin).can_ingest_url(settings) is False
    assert _principal(Role.user).can_ingest_url(settings) is False


# ---------- ToolSpec auth posture ----------


def test_create_course_draft_spec_is_user_posture():
    # S1.6: create_course_draft moves instructor → user.
    assert _spec("create_course_draft").auth == "user"


def test_ingest_url_to_draft_spec_stays_admin():
    # DR-M12: ingest stays admin-only.
    assert _spec("ingest_url_to_draft").auth == "admin"


# ---------- _enforce_auth on the `user` posture ----------


def test_enforce_auth_user_posture_allows_active_user():
    spec = _spec("create_course_draft")
    # No raise = allowed.
    mcp_server._enforce_auth(spec, _principal(Role.user))


def test_enforce_auth_user_posture_allows_legacy_instructor():
    spec = _spec("create_course_draft")
    mcp_server._enforce_auth(spec, _principal(Role.instructor))


def test_enforce_auth_admin_posture_denies_non_admin():
    spec = _spec("ingest_url_to_draft")
    with pytest.raises(ForbiddenError) as exc:
        mcp_server._enforce_auth(spec, _principal(Role.user))
    assert exc.value.code == "mcp.role.admin_required"


# ---------- _require_author (the tool-body write gate) ----------


def test_require_author_allows_active_user():
    mcp_tools._require_author(_principal(Role.user))


def test_require_author_allows_legacy_instructor():
    mcp_tools._require_author(_principal(Role.instructor))


def test_require_author_denies_suspended_with_author_required_code():
    with pytest.raises(ForbiddenError) as exc:
        mcp_tools._require_author(_principal(Role.user, is_active=False))
    assert exc.value.code == "mcp.writes.author_required"
