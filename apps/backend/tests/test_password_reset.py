"""Password reset request + confirm."""

from __future__ import annotations

from httpx import AsyncClient

from app.services import password_reset as reset


async def test_request_always_ok_even_for_unknown(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@lumen.test"}
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_reset_round_trip(client: AsyncClient, make_user, db_session) -> None:
    user = await make_user(email="r@lumen.test", password="OldPassword!1234")
    token = reset.make_token(user)

    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "NewPassword!1234"},
    )
    assert r.status_code == 200

    # Old password no longer works, new does.
    bad = await client.post(
        "/api/v1/auth/login", json={"email": "r@lumen.test", "password": "OldPassword!1234"}
    )
    assert bad.status_code == 401
    ok = await client.post(
        "/api/v1/auth/login", json={"email": "r@lumen.test", "password": "NewPassword!1234"}
    )
    assert ok.status_code == 200


async def test_reset_token_is_single_use(client: AsyncClient, make_user) -> None:
    user = await make_user(email="su@lumen.test", password="OldPassword!1234")
    token = reset.make_token(user)

    r1 = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "NewPassword!1234"},
    )
    assert r1.status_code == 200

    r2 = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": "AnotherPassword!1234"},
    )
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "auth.reset_used"


async def test_reset_rejects_garbage(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "garbage.token.value", "password": "NewPassword!1234"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.reset_invalid"
