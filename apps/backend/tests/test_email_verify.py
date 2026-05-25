"""Email verification round-trip."""

from __future__ import annotations

from httpx import AsyncClient

from app.services import email_verify as verify


async def test_register_user_is_unverified(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "u1@lumen.test", "password": "Password!1234", "full_name": "U1"},
    )
    assert r.status_code == 201
    assert r.json()["email_verified_at"] is None


async def test_confirm_marks_verified(client: AsyncClient, make_user, db_session) -> None:
    user = await make_user(email="ver@lumen.test", password="Password!1234")
    assert user.email_verified_at is None
    token = verify.make_token(user)

    r = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert r.status_code == 200

    # Login and inspect /me
    login = await client.post(
        "/api/v1/auth/login", json={"email": "ver@lumen.test", "password": "Password!1234"}
    )
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.json()["email_verified_at"] is not None


async def test_confirm_is_idempotent(client: AsyncClient, make_user) -> None:
    user = await make_user(email="ver2@lumen.test")
    token = verify.make_token(user)
    a = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    b = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert a.status_code == 200 and b.status_code == 200


async def test_stale_token_after_email_change_rejected(
    client: AsyncClient, make_user, db_session
) -> None:
    user = await make_user(email="ver3@lumen.test")
    token = verify.make_token(user)

    user.email = "renamed@lumen.test"
    await db_session.commit()

    r = await client.post("/api/v1/auth/verify/confirm", json={"token": token})
    assert r.status_code == 401
    assert r.json()["error"]["code"] in {"verify.invalid", "verify.stale"}


async def test_request_resend_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/verify/request")
    assert r.status_code == 401


async def test_confirm_bad_token(client: AsyncClient) -> None:
    r = await client.post("/api/v1/auth/verify/confirm", json={"token": "garbage.garbage.garbage"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "verify.invalid"
