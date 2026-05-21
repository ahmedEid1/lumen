"""Active sessions endpoints."""

from __future__ import annotations

from httpx import AsyncClient


async def test_sessions_lists_after_login(client: AsyncClient, make_user) -> None:
    await make_user(email="s1@lumen.test", password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "s1@lumen.test", "password": "Password!1234"}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = await client.get("/api/v1/users/me/sessions", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 1
    assert all(row["revoked_at"] is None for row in rows)
    assert "user_agent" in rows[0] and "ip_address" in rows[0]


async def test_revoke_one_session(client: AsyncClient, make_user) -> None:
    await make_user(email="s2@lumen.test", password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "s2@lumen.test", "password": "Password!1234"}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    sessions = (await client.get("/api/v1/users/me/sessions", headers=h)).json()
    sid = sessions[0]["id"]

    r = await client.delete(f"/api/v1/users/me/sessions/{sid}", headers=h)
    assert r.status_code == 200

    after = (await client.get("/api/v1/users/me/sessions", headers=h)).json()
    revoked = [s for s in after if s["id"] == sid]
    assert revoked and revoked[0]["revoked_at"] is not None


async def test_revoke_unknown_session_404(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.delete("/api/v1/users/me/sessions/does-not-exist", headers=h)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "session.not_found"


async def test_revoke_all_sessions(client: AsyncClient, make_user) -> None:
    await make_user(email="s3@lumen.test", password="Password!1234")
    # Log in twice to create two refresh tokens
    for _ in range(2):
        await client.post(
            "/api/v1/auth/login", json={"email": "s3@lumen.test", "password": "Password!1234"}
        )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "s3@lumen.test", "password": "Password!1234"}
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    sessions = (await client.get("/api/v1/users/me/sessions", headers=h)).json()
    active_before = [s for s in sessions if s["revoked_at"] is None]
    assert len(active_before) >= 2

    r = await client.delete("/api/v1/users/me/sessions", headers=h)
    assert r.status_code == 200

    after = (await client.get("/api/v1/users/me/sessions", headers=h)).json()
    assert all(s["revoked_at"] is not None for s in after)


async def test_sessions_require_auth(client: AsyncClient) -> None:
    r = await client.get("/api/v1/users/me/sessions")
    assert r.status_code == 401
