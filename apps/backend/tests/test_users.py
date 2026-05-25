"""Profile, password change, GDPR export, account delete."""

from __future__ import annotations

from httpx import AsyncClient


async def test_get_and_update_profile(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.get("/api/v1/users/me", headers=h)
    assert r.status_code == 200
    assert r.json()["full_name"] == "Test User"

    upd = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Updated", "bio": "hi", "avatar_url": "https://x.test/a.png"},
        headers=h,
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["full_name"] == "Updated"
    assert body["bio"] == "hi"
    assert body["avatar_url"] == "https://x.test/a.png"


async def test_change_password_requires_current(client: AsyncClient, make_user) -> None:
    await make_user(email="pw@lumen.test", password="OldPassword!1234")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "pw@lumen.test", "password": "OldPassword!1234"}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    bad = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "wrong", "new_password": "NewPassword!1234"},
        headers=h,
    )
    assert bad.status_code == 401

    ok = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "OldPassword!1234", "new_password": "NewPassword!1234"},
        headers=h,
    )
    assert ok.status_code == 200

    # old password no longer works
    fail = await client.post(
        "/api/v1/auth/login",
        json={"email": "pw@lumen.test", "password": "OldPassword!1234"},
    )
    assert fail.status_code == 401
    relog = await client.post(
        "/api/v1/auth/login",
        json={"email": "pw@lumen.test", "password": "NewPassword!1234"},
    )
    assert relog.status_code == 200


async def test_change_password_rejects_same(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "Password!1234"},
        headers=h,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "auth.password_reused"


async def test_gdpr_export(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.get("/api/v1/users/me/export", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "profile" in body and "counts" in body
    assert body["counts"]["enrollments"] == 0


async def test_delete_account(client: AsyncClient, make_user) -> None:
    await make_user(email="bye@lumen.test", password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "bye@lumen.test", "password": "Password!1234"}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    bad = await client.request(
        "DELETE", "/api/v1/users/me", headers=h, json={"password": "wrong"}
    )
    assert bad.status_code == 401

    ok = await client.request(
        "DELETE", "/api/v1/users/me", headers=h, json={"password": "Password!1234"}
    )
    assert ok.status_code == 200

    # Login is impossible afterwards.
    fail = await client.post(
        "/api/v1/auth/login", json={"email": "bye@lumen.test", "password": "Password!1234"}
    )
    assert fail.status_code == 401


async def test_delete_account_kills_outstanding_access_token(
    client: AsyncClient, make_user
) -> None:
    """Rebuild Fix B5 invariant: the access token issued *before* the
    delete must not be usable after the delete commits. Otherwise a
    stolen token (or a tab the user just closed) still hits /me-like
    endpoints for up to access-token TTL.

    The implementation flips ``user.is_active`` to False as part of the
    delete; ``get_current_user_optional`` returns None for inactive
    users, which the auth dep escalates to 401. This test pins the
    behaviour so a future refactor that drops the ``is_active`` check
    fails loudly.
    """
    await make_user(email="kill-access@lumen.test", password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "kill-access@lumen.test", "password": "Password!1234"},
    )
    access = login.json()["access_token"]
    h = {"Authorization": f"Bearer {access}"}

    pre = await client.get("/api/v1/users/me", headers=h)
    assert pre.status_code == 200

    await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=h,
        json={"password": "Password!1234"},
    )

    # Same access token, post-delete: must be rejected.
    post = await client.get("/api/v1/users/me", headers=h)
    assert post.status_code == 401


async def test_delete_account_revokes_refresh_token(
    client: AsyncClient, make_user
) -> None:
    """Rebuild Fix B5 invariant: refresh tokens issued before the
    delete must be unusable afterwards.

    The implementation calls ``revoke_all_refresh_tokens(user.id)``
    inside the delete handler, which bulk-updates ``revoked_at`` on
    every active row. The refresh endpoint rejects revoked tokens
    with 401. Pinned here so a refactor that skips the bulk-revoke
    leaves a regression test instead of a stale audit finding.
    """
    await make_user(
        email="kill-refresh@lumen.test", password="Password!1234"
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "kill-refresh@lumen.test", "password": "Password!1234"},
    )
    refresh_cookie = login.cookies.get("refresh") or login.cookies.get(
        "__Host-refresh"
    )
    assert refresh_cookie, "login must set a refresh cookie"
    access = login.json()["access_token"]
    h = {"Authorization": f"Bearer {access}"}

    await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=h,
        json={"password": "Password!1234"},
    )

    # The same refresh cookie must no longer mint an access token.
    refresh_response = await client.post(
        "/api/v1/auth/refresh", cookies={"refresh": refresh_cookie}
    )
    assert refresh_response.status_code == 401
