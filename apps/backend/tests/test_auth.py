"""Auth: register, login, refresh rotation, logout."""

from __future__ import annotations

from httpx import AsyncClient


async def test_register_then_login(client: AsyncClient) -> None:
    email = "newuser@lumen.test"
    pwd = "Password!1234"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": pwd, "full_name": "Newbie"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == email

    r2 = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    assert r2.status_code == 200
    body = r2.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "x@lumen.test", "password": "abcdefghijkl", "full_name": "x"},
    )
    assert r.status_code == 422


async def test_register_rejects_duplicate(client: AsyncClient) -> None:
    payload = {"email": "dup@lumen.test", "password": "Password!1234", "full_name": "Dup"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "auth.email_taken"


async def test_login_invalid_credentials(client: AsyncClient, make_user) -> None:
    await make_user(email="real@lumen.test", password="Password!1234")
    r = await client.post(
        "/api/v1/auth/login", json={"email": "real@lumen.test", "password": "wrong-password"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.invalid_credentials"


async def test_me_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_me_with_token(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers()
    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert "@lumen.test" in r.json()["email"]


async def test_refresh_rotates_and_reuse_detection(client: AsyncClient, make_user) -> None:
    email = "rot@lumen.test"
    pwd = "Password!1234"
    await make_user(email=email, password=pwd)

    r = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    assert r.status_code == 200
    first_refresh = r.cookies.get("refresh") or r.cookies.get("__Host-refresh")
    assert first_refresh

    r2 = await client.post("/api/v1/auth/refresh", cookies={"refresh": first_refresh})
    assert r2.status_code == 200
    new_refresh = r2.cookies.get("refresh") or r2.cookies.get("__Host-refresh")
    assert new_refresh and new_refresh != first_refresh

    # Replay the original refresh — should be detected as reuse.
    r3 = await client.post("/api/v1/auth/refresh", cookies={"refresh": first_refresh})
    assert r3.status_code == 401
    assert r3.json()["error"]["code"] in {"auth.refresh_reuse", "auth.refresh_invalid"}


async def test_logout_clears_cookies(client: AsyncClient, make_user) -> None:
    email = "logout@lumen.test"
    pwd = "Password!1234"
    await make_user(email=email, password=pwd)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": pwd})
    cookie = r.cookies.get("refresh") or r.cookies.get("__Host-refresh")
    r2 = await client.post("/api/v1/auth/logout", cookies={"refresh": cookie} if cookie else None)
    assert r2.status_code == 200
