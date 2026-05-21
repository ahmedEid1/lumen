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
