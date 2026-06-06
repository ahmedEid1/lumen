"""S1.9 — the JWT `role` claim is authorization-inert (FR-MIG-04, ADR-0025 §D6).

Authorization always re-reads the live `User.role` from the DB per request
(`deps.py`); `decode_token` never inspects `role`. So a stale token claiming
`instructor` (or any other role) grants exactly what the live DB row grants —
nothing more. This is the migration-safety invariant that lets the role
collapse roll out without invalidating in-flight tokens.

The `normalize_role` tests are pure (no DB); the stale-token tests are
DB-backed (they load the live row) and run under `make test.api`.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, decode_token, normalize_role
from app.models.user import Role

# ---------- normalize_role (pure) ----------


def test_normalize_role_maps_legacy_to_user():
    assert normalize_role("instructor") == Role.user
    assert normalize_role("student") == Role.user


def test_normalize_role_maps_admin_to_admin():
    assert normalize_role("admin") == Role.admin
    assert normalize_role(Role.admin) == Role.admin


def test_normalize_role_maps_garbage_and_none_to_user():
    assert normalize_role("garbage") == Role.user
    assert normalize_role("") == Role.user
    assert normalize_role(None) == Role.user


def test_normalize_role_never_escalates_to_admin():
    # No legacy/unknown value may ever normalise to admin (the only escalation
    # guard that matters for display rendering).
    for value in ("instructor", "student", "superuser", "Admin ", "ADMIN"):
        norm = normalize_role(value)
        if value.strip().lower() == "admin":
            assert norm == Role.admin
        else:
            assert norm != Role.admin


def test_decode_token_does_not_validate_role():
    # A token with a bogus role still decodes — role is never validated at
    # decode time (authz re-reads the DB).
    token, _ = create_access_token(subject="user_x", role="bogus")
    payload = decode_token(token)
    assert payload["sub"] == "user_x"
    assert payload["role"] == "bogus"


# ---------- stale-token inert-claim (DB-backed) ----------


@pytest.mark.asyncio
async def test_stale_instructor_token_grants_no_admin(client: AsyncClient, make_user) -> None:
    # A live `user`-role row + a token *claiming* instructor → still no admin
    # power. The claim is provably inert.
    user = await make_user(email=f"inert-{uuid.uuid4().hex[:8]}@lumen.test", role=Role.user)
    token, _ = create_access_token(subject=user.id, role="instructor")
    headers = {"Authorization": f"Bearer {token}"}

    # An admin-only route → 403 (the instructor claim does NOT grant admin).
    r = await client.get("/api/v1/admin/stats", headers=headers)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_stale_instructor_token_authors_via_live_row(client: AsyncClient, make_user) -> None:
    # The same stale-`instructor`-claim token CAN author — but because the
    # live row is an active user, not because of the claim.
    user = await make_user(email=f"inert2-{uuid.uuid4().hex[:8]}@lumen.test", role=Role.user)
    token, _ = create_access_token(subject=user.id, role="instructor")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/v1/courses/mine", headers=headers)
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_real_admin_row_with_user_claim_still_admin(client: AsyncClient, make_user) -> None:
    # Symmetry check: a live admin row + a token claiming `user` is STILL
    # admin — authz reads the DB, not the claim.
    admin = await make_user(email=f"realadmin-{uuid.uuid4().hex[:8]}@lumen.test", role=Role.admin)
    token, _ = create_access_token(subject=admin.id, role="user")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/v1/admin/stats", headers=headers)
    assert r.status_code == 200, r.text
