"""Regression: HIBP breach-list check on every password-setting path.

The unified structural strength policy is paired with a HIBP /
breach-list lookup using k-anonymity (only the first 5 chars of
SHA-1 leave the process). The gate applies to register,
password-reset confirm, and change-password.

The feature is opt-in via ``hibp_enabled`` — test infra defaults to
disabled to avoid hitting api.pwnedpasswords.com during ``make test``,
so each test that exercises the gate flips the flag explicitly and
stubs ``httpx.AsyncClient`` to return a deterministic response.

We also cover the fail-open posture: if HIBP times out or 5xxs, the
caller must NOT be blocked. Refusing to let users register because an
external service is down would be its own incident.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services import password_hibp


def _sha1_split(password: str) -> tuple[str, str]:
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    return digest[:5], digest[5:]


class _StubTransport(httpx.AsyncBaseTransport):
    """Pluggable httpx transport so we can pin HIBP responses per-test."""

    def __init__(self, responder):
        self._responder = responder
        self.calls: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self._responder(request)


@pytest.fixture
def hibp_enabled(monkeypatch):
    monkeypatch.setenv("HIBP_ENABLED", "true")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _patch_client(monkeypatch, responder):
    """Make every ``httpx.AsyncClient(...)`` use our stub transport."""
    real_init = httpx.AsyncClient.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = _StubTransport(responder)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)


# ---------------- pure helper ----------------


async def test_is_pwned_returns_false_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HIBP_ENABLED", "false")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        assert await password_hibp.is_pwned("Password!1234") is False
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]


async def test_is_pwned_true_when_suffix_present(monkeypatch, hibp_enabled) -> None:
    password = "Password!1234"
    _, suffix = _sha1_split(password)
    body = f"AAAAA:0\r\n{suffix}:42\r\nBBBBB:7\r\n"

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    _patch_client(monkeypatch, _respond)
    assert await password_hibp.is_pwned(password) is True


async def test_is_pwned_false_when_suffix_absent(monkeypatch, hibp_enabled) -> None:
    body = "AAAAA:0\r\nBBBBB:7\r\n"

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    _patch_client(monkeypatch, _respond)
    assert await password_hibp.is_pwned("Password!1234") is False


async def test_is_pwned_ignores_padding_count_zero(monkeypatch, hibp_enabled) -> None:
    """HIBP's k-anonymity padding entries have count=0 — those exist
    only to defeat traffic-analysis and must NOT trigger a false-positive
    'breached' verdict when the suffix happens to match a padding row."""
    password = "Password!1234"
    _, suffix = _sha1_split(password)
    body = f"{suffix}:0\r\nOTHER:5\r\n"

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    _patch_client(monkeypatch, _respond)
    assert await password_hibp.is_pwned(password) is False


async def test_fail_open_on_timeout(monkeypatch, hibp_enabled) -> None:
    def _respond(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated", request=request)

    _patch_client(monkeypatch, _respond)
    # MUST return False — refusing to let users register because HIBP
    # is slow is its own outage.
    assert await password_hibp.is_pwned("anything") is False


async def test_fail_open_on_5xx(monkeypatch, hibp_enabled) -> None:
    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    _patch_client(monkeypatch, _respond)
    assert await password_hibp.is_pwned("anything") is False


async def test_only_prefix_leaves_the_process(monkeypatch, hibp_enabled) -> None:
    """Pin the k-anonymity contract: the request URL contains only the
    first 5 hex chars of SHA-1, not the suffix and not the password."""
    captured: list[httpx.Request] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="AAAAA:0\r\n")

    _patch_client(monkeypatch, _respond)
    password = "Password!1234"
    prefix, suffix = _sha1_split(password)
    await password_hibp.is_pwned(password)
    assert captured, "no HIBP request issued"
    url = str(captured[0].url)
    assert prefix in url
    assert suffix not in url
    assert password not in url


# ---------------- end-to-end across the three sites ----------------


async def test_register_rejects_pwned_password(
    monkeypatch, hibp_enabled, client: AsyncClient
) -> None:
    password = "Password!1234"
    _, suffix = _sha1_split(password)

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"{suffix}:99\r\n")

    _patch_client(monkeypatch, _respond)
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "pwn@lumen.test",
            "password": password,
            "full_name": "Test",
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "auth.password_breached"


async def test_password_reset_rejects_pwned_password(
    monkeypatch, hibp_enabled, client: AsyncClient, make_user
) -> None:
    user = await make_user(email="rpwn@lumen.test", password="OldPassword!1234")
    from app.services import password_reset as reset

    token = reset.make_token(user)

    new_password = "Compromised!!42"
    _, suffix = _sha1_split(new_password)

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"{suffix}:1\r\n")

    _patch_client(monkeypatch, _respond)
    r = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "password": new_password},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "auth.password_breached"


async def test_change_password_rejects_pwned_password(
    monkeypatch, hibp_enabled, client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    new_password = "NewBreached!42"
    _, suffix = _sha1_split(new_password)

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"{suffix}:7\r\n")

    _patch_client(monkeypatch, _respond)
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={
            "current_password": "Password!1234",
            "new_password": new_password,
        },
        headers=h,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "auth.password_breached"


async def test_register_succeeds_when_password_not_breached(
    monkeypatch, hibp_enabled, client: AsyncClient
) -> None:
    """Happy path with the flag ON — verify the gate doesn't accidentally
    block legitimate passwords."""

    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="AAAAA:0\r\nBBBBB:1\r\n")

    _patch_client(monkeypatch, _respond)
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "clean@lumen.test",
            "password": "Password!1234",
            "full_name": "Clean",
        },
    )
    assert r.status_code == 201, r.text


async def test_register_succeeds_when_hibp_disabled(
    client: AsyncClient,
) -> None:
    """Default config: HIBP off, no network call, no rejection."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "off@lumen.test",
            "password": "Password!1234",
            "full_name": "Off",
        },
    )
    assert r.status_code == 201, r.text
