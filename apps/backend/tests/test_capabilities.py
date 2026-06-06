"""S7pre.2 — capability predicates (ADR-0025 §D2, R-CAP).

Pure functions over ``(User, Settings)``. No per-user override table —
suspension (``is_active=False``) is the single revocation axis (R-CAP).
These are unit tests with hand-built ``User`` instances; no DB.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.user import Role, User
from app.services import capabilities as cap

# S7-pre runs *before* the S1 enum widen, so the non-admin role here is the
# current default (``student``). The capability predicates are role-agnostic
# for non-admins (they key on ``is_active`` + ``is_admin()``), so this stays
# correct once S1 collapses ``student`` → ``user``.
NON_ADMIN = Role.student


def _user(*, role: Role = NON_ADMIN, is_active: bool = True, uid: str = "u_1") -> User:
    u = User(email="a@lumen.test", password_hash="x", full_name="A", role=role)
    u.id = uid
    u.is_active = is_active
    return u


def _settings(*, ingest_url_enabled: bool = False, mcp_authoring_enabled: bool = True):
    # A duck-typed stand-in is enough — the predicates only read two flags.
    return SimpleNamespace(
        ingest_url_enabled=ingest_url_enabled,
        mcp_authoring_enabled=mcp_authoring_enabled,
    )


def test_active_user_can_author_clone_publish():
    u = _user(role=NON_ADMIN, is_active=True)
    assert cap.can_author(u) is True
    assert cap.can_clone(u) is True
    assert cap.can_publish_public(u) is True


def test_active_user_can_use_byok():
    assert cap.can_use_byok(_user()) is True


def test_admin_passes_every_capability():
    a = _user(role=Role.admin, is_active=True)
    assert cap.can_author(a)
    assert cap.can_clone(a)
    assert cap.can_publish_public(a)
    assert cap.can_use_byok(a)
    assert cap.can_use_mcp_authoring(a, _settings())
    # ingest is admin + flag — admin still needs the flag ON.
    assert cap.can_ingest_url(a, _settings(ingest_url_enabled=True)) is True
    assert cap.can_ingest_url(a, _settings(ingest_url_enabled=False)) is False


def test_suspended_user_has_no_capabilities():
    """is_active=False → every predicate is False (R-CAP single revocation)."""
    s = _user(role=NON_ADMIN, is_active=False)
    a = _user(role=Role.admin, is_active=False)
    settings_open = _settings(ingest_url_enabled=True, mcp_authoring_enabled=True)
    course = SimpleNamespace(owner_id=s.id)
    for u in (s, a):
        assert cap.can_author(u) is False
        assert cap.can_clone(u) is False
        assert cap.can_publish_public(u) is False
        assert cap.can_use_byok(u) is False
        assert cap.can_use_mcp_authoring(u, settings_open) is False
        assert cap.can_ingest_url(u, settings_open) is False
        assert cap.can_view_course_analytics(u, course) is False


def test_can_ingest_url_admin_and_flag_only():
    """can_ingest_url = active AND admin AND settings.ingest_url_enabled."""
    admin = _user(role=Role.admin)
    regular = _user(role=NON_ADMIN)
    # Non-admin never ingests, even with the flag on.
    assert cap.can_ingest_url(regular, _settings(ingest_url_enabled=True)) is False
    # Admin only with the flag on.
    assert cap.can_ingest_url(admin, _settings(ingest_url_enabled=True)) is True
    assert cap.can_ingest_url(admin, _settings(ingest_url_enabled=False)) is False


def test_can_use_mcp_authoring_flag_gated():
    u = _user(role=NON_ADMIN)
    assert cap.can_use_mcp_authoring(u, _settings(mcp_authoring_enabled=True)) is True
    assert cap.can_use_mcp_authoring(u, _settings(mcp_authoring_enabled=False)) is False


def test_can_view_course_analytics_owner_or_admin():
    owner = _user(role=NON_ADMIN, uid="owner_1")
    other = _user(role=NON_ADMIN, uid="other_1")
    admin = _user(role=Role.admin, uid="admin_1")
    course = SimpleNamespace(owner_id="owner_1")
    assert cap.can_view_course_analytics(owner, course) is True
    assert cap.can_view_course_analytics(other, course) is False
    assert cap.can_view_course_analytics(admin, course) is True


def test_real_settings_defaults_keep_ingest_closed():
    """The real Settings object defaults ingest closed, mcp authoring open."""
    from app.core.config import Settings

    s = Settings()
    assert s.ingest_url_enabled is False
    assert s.mcp_authoring_enabled is True
    admin = _user(role=Role.admin)
    # With production-shaped defaults, even admin cannot ingest.
    assert cap.can_ingest_url(admin, s) is False
    assert cap.can_use_mcp_authoring(admin, s) is True
