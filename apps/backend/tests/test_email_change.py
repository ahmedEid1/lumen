"""Two-step email change flow.

* /users/me/email/request: verifies current password, checks new
  address isn't already taken, mints a JWT bound to (user.id, new
  email, current pwd hash), and sends a link to the *new* mailbox.
* /users/me/email/confirm: exchanges token → applies the change,
  revokes every refresh token so parallel sessions get booted.

Token is bound to the current password hash so a password rotation
between request and confirm invalidates outstanding email-change
tokens (same posture password-reset uses).
"""

from __future__ import annotations

from httpx import AsyncClient

from app.services import email_change as email_change_service


async def test_request_rejects_wrong_password(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/email/request",
        json={"new_email": "new@lumen.test", "current_password": "wrong"},
        headers=h,
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.invalid_credentials"


async def test_request_rejects_taken_email(client: AsyncClient, auth_headers, make_user) -> None:
    await make_user(email="taken@lumen.test")
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/email/request",
        json={"new_email": "taken@lumen.test", "current_password": "Password!1234"},
        headers=h,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "auth.email_taken"


async def test_request_same_email_is_noop_ok(client: AsyncClient, auth_headers, make_user) -> None:
    """Requesting a change to the address you already have is a no-op
    success — the UI shouldn't have to special-case it."""
    user = await make_user(email="me@lumen.test", password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = await client.post(
        "/api/v1/users/me/email/request",
        json={"new_email": "me@lumen.test", "current_password": "Password!1234"},
        headers=h,
    )
    assert r.status_code == 200


async def test_request_and_confirm_round_trip(client: AsyncClient, make_user, db_session) -> None:
    user = await make_user(email="before@lumen.test", password="Password!1234")
    token = email_change_service.make_token(user, new_email="after@lumen.test")

    r = await client.post("/api/v1/users/me/email/confirm", json={"token": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "after@lumen.test"

    # Old email no longer logs in.
    fail = await client.post(
        "/api/v1/auth/login",
        json={"email": "before@lumen.test", "password": "Password!1234"},
    )
    assert fail.status_code == 401
    # New email does.
    ok = await client.post(
        "/api/v1/auth/login",
        json={"email": "after@lumen.test", "password": "Password!1234"},
    )
    assert ok.status_code == 200


async def test_confirm_after_password_rotation_is_stale(client: AsyncClient, make_user) -> None:
    user = await make_user(email="rot@lumen.test", password="Password!1234")
    token = email_change_service.make_token(user, new_email="dst@lumen.test")

    # User rotates password before clicking the email link.
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    chg = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "RotatedPassword!42"},
        headers=h,
    )
    assert chg.status_code == 200

    # Now the email-change token (bound to the OLD password hash) is stale.
    r = await client.post("/api/v1/users/me/email/confirm", json={"token": token})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "email_change.stale"


async def test_confirm_clashes_if_someone_grabbed_the_address(
    client: AsyncClient, make_user
) -> None:
    """Between request and confirm, another account could have
    registered the target email. We re-check uniqueness at confirm."""
    user = await make_user(email="src@lumen.test", password="Password!1234")
    token = email_change_service.make_token(user, new_email="contested@lumen.test")

    # Someone else grabs it.
    await make_user(email="contested@lumen.test")

    r = await client.post("/api/v1/users/me/email/confirm", json={"token": token})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "auth.email_taken"


async def test_confirm_garbage_token_rejected(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/users/me/email/confirm", json={"token": "garbage.garbage.garbage"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "email_change.invalid"


async def test_confirm_revokes_all_refresh_tokens(client: AsyncClient, make_user) -> None:
    """An email change is a significant security event — every parallel
    session must be booted so the user re-authenticates with the new
    credentials."""
    user = await make_user(email="sess@lumen.test", password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    assert login.status_code == 200
    # AsyncClient persists the refresh cookie from /login.
    token = email_change_service.make_token(user, new_email="moved@lumen.test")
    confirm = await client.post("/api/v1/users/me/email/confirm", json={"token": token})
    assert confirm.status_code == 200

    # The old refresh cookie no longer works.
    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 401
