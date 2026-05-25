"""Regression: every endpoint that accepts a *new* password enforces the
same strength policy.

Before iteration 39 only ``RegisterRequest`` had the
"mix character classes" check. ``PasswordResetConfirm`` and
``ChangePasswordRequest`` enforced just ``min_length=12``. That meant a
user who registered with ``Password!1234`` could quietly downgrade to
``password12345`` via either the reset flow (anyone who could request a
reset token) or the in-app change-password page. We extracted
``validate_password_strength`` into ``app.schemas.auth`` and wired it to
all three.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.schemas.auth import (
    PasswordResetConfirm,
    RegisterRequest,
    validate_password_strength,
)
from app.services import password_reset as reset

# ---------------- Pure validator ----------------


@pytest.mark.parametrize(
    "weak",
    [
        "password1234",  # all lowercase + digits, registration would reject
        "abcdefghijkl",  # all lowercase letters, length OK
        "1234567890ab",  # all alphanumeric lowercase
    ],
)
def test_validate_rejects_weak(weak: str) -> None:
    with pytest.raises(ValueError):
        validate_password_strength(weak)


@pytest.mark.parametrize(
    "strong",
    [
        "Password!1234",  # upper + lower + digit + symbol
        "MixedCase1234",  # upper + lower + digit
        "all_lower_with_!",  # symbol breaks isalnum
    ],
)
def test_validate_accepts_strong(strong: str) -> None:
    assert validate_password_strength(strong) == strong


def test_register_schema_uses_shared_policy() -> None:
    with pytest.raises(ValueError):
        RegisterRequest(
            email="x@lumen.test",
            password="alllowercase1",  # weak — was already rejected
            full_name="X",
        )


def test_reset_confirm_schema_uses_shared_policy() -> None:
    with pytest.raises(ValueError):
        # The shared policy rejects this; a bare `min_length=12` would let it through.
        PasswordResetConfirm(token="x" * 20, password="alllowercase1")


# ---------------- End-to-end paths ----------------


async def test_password_reset_rejects_weak_password(client: AsyncClient, make_user) -> None:
    user = await make_user(email="pw-reset@lumen.test", password="OldPassword!1234")
    token = reset.make_token(user)
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "alllowercase1"},
    )
    assert r.status_code == 422
    # Old password still works (reset didn't go through).
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "pw-reset@lumen.test", "password": "OldPassword!1234"},
    )
    assert ok.status_code == 200


async def test_change_password_rejects_weak_password(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "alllowercase1"},
        headers=h,
    )
    assert r.status_code == 422


async def test_change_password_still_accepts_strong_password(
    client: AsyncClient, auth_headers
) -> None:
    # Sanity: tightening the policy didn't break the happy path.
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!9876"},
        headers=h,
    )
    assert r.status_code == 200
