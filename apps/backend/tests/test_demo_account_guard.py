"""L45: the shared demo login can learn and build, but can't lock other
visitors out, store API keys or post anything public."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

DEMO_EMAIL = "demo@lumen.test"
DEMO_PASSWORD = "Demo!2026"


async def _login(client: AsyncClient, make_user, email: str, password: str) -> dict:
    await make_user(email=email, password=password)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


WRITES = [
    ("patch", "/api/v1/users/me", {"full_name": "Hijacked"}),
    (
        "post",
        "/api/v1/users/me/change-password",
        {"current_password": DEMO_PASSWORD, "new_password": "Another!2026x"},
    ),
    ("delete", "/api/v1/users/me/sessions", None),
    (
        "post",
        "/api/v1/users/me/email/request",
        {"new_email": "x@example.com", "current_password": DEMO_PASSWORD},
    ),
    ("delete", "/api/v1/users/me", None),
    (
        "put",
        "/api/v1/me/llm-credentials/groq",
        {"api_key": "gsk_test_not_real", "model": "openai/gpt-oss-20b"},
    ),
    ("put", "/api/v1/courses/some-course/reviews", {"rating": 5, "body": "great"}),
    ("post", "/api/v1/courses/some-course/discussions", {"title": "spam", "body": "spam"}),
    ("post", "/api/v1/courses/some-course/share", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_demo_account_is_read_only_for_account_and_public_writes(
    client: AsyncClient, make_user, method: str, path: str, body: dict | None
) -> None:
    headers = await _login(client, make_user, DEMO_EMAIL, DEMO_PASSWORD)
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    r = await client.request(method.upper(), path, **kwargs)
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert r.json()["error"]["code"] == "demo.read_only"


async def test_demo_password_still_works_after_a_change_attempt(
    client: AsyncClient, make_user
) -> None:
    headers = await _login(client, make_user, DEMO_EMAIL, DEMO_PASSWORD)
    await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": DEMO_PASSWORD, "new_password": "Another!2026x"},
        headers=headers,
    )
    client.cookies.clear()
    again = await client.post(
        "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    )
    assert again.status_code == 200


async def test_other_users_are_not_affected(client: AsyncClient, make_user) -> None:
    headers = await _login(client, make_user, "someone@example.com", "Password!1234")
    r = await client.patch("/api/v1/users/me", json={"full_name": "Renamed"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Renamed"


# ---------- L65: bootstrap-admin can't recreate the published admin login ----------


@pytest.mark.parametrize(
    ("email", "password"),
    [("admin@lumen.test", "Fresh!Passw0rd"), ("me@example.com", "Admin!2026")],
)
def test_bootstrap_admin_refuses_the_public_login_in_production(
    monkeypatch, email: str, password: str
) -> None:
    import typer

    from app import cli
    from app.core.config import Environment

    monkeypatch.setattr(cli.get_settings(), "env", Environment.production)
    with pytest.raises(typer.Exit):
        cli._refuse_public_admin_in_prod(email, password)


def test_bootstrap_admin_defaults_still_work_locally(monkeypatch) -> None:
    from app import cli
    from app.core.config import Environment

    monkeypatch.setattr(cli.get_settings(), "env", Environment.development)
    cli._refuse_public_admin_in_prod("admin@lumen.test", "Admin!2026")  # no exit
