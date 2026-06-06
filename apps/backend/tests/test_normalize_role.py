"""S7pre.4 — normalize_role display helper (ADR-0025 §D6, FR-MIG-04).

``normalize_role`` maps any legacy/unknown role string → ``Role`` for
*display only*. Authorization never trusts the JWT ``role`` claim — the
deps path re-reads the live ``User.role`` from the DB on every request
(``deps.py``). This test documents that inert-claim invariant: a stale or
forged ``role`` claim grants nothing because it is never read for authz.
"""

from __future__ import annotations

from app.core.security import create_access_token, decode_token, normalize_role
from app.models.user import Role


def test_admin_maps_to_admin():
    assert normalize_role("admin") is Role.admin
    assert normalize_role(Role.admin) is Role.admin


def test_legacy_roles_map_to_user_or_admin():
    # Legacy/unknown non-admin strings collapse to the new default role.
    # During S7-pre the enum still has ``student``/``instructor`` and no
    # ``user`` member; the helper maps everything-non-admin to the lowest
    # privilege available, and exposes ``user`` once S1 widens the enum.
    for raw in ("student", "instructor", "teacher", "guest", "", "USER", "Admin "):
        result = normalize_role(raw)
        assert isinstance(result, Role)
        if raw.strip().lower() == "admin":
            assert result is Role.admin
        else:
            assert result is not Role.admin


def test_none_maps_to_non_admin():
    assert normalize_role(None) is not Role.admin


def test_unknown_never_grants_admin():
    """The core safety property: no legacy/unknown value normalizes to admin."""
    for raw in ("superuser", "root", "instructor", "owner", "moderator"):
        assert normalize_role(raw) is not Role.admin


def test_inert_claim_invariant_forged_role_in_token():
    """A token whose ``role`` claim is forged-to-admin still decodes the claim
    verbatim — authz must NOT key on it. We assert the claim round-trips
    (it is display-only data) and that normalize_role of a non-admin DB role
    is what authorization would actually use.

    This documents FR-MIG-04: the claim is inert; the DB row governs. The
    deps layer (tested separately, DB-backed) re-reads ``User.role``.
    """
    token, _ = create_access_token(subject="u_1", role="admin")
    payload = decode_token(token)
    # The claim is present and trusted only for *display*.
    assert payload["role"] == "admin"
    # But normalize_role of a legacy/unknown claim is the inert path: a
    # token minted with a legacy role string never resolves to admin.
    legacy_token, _ = create_access_token(subject="u_2", role="instructor")
    legacy_payload = decode_token(legacy_token)
    assert normalize_role(legacy_payload["role"]) is not Role.admin
