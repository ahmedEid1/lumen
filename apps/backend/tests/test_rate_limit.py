"""Rate-limited auth endpoints respond with 429 after the bucket drains."""

from __future__ import annotations

from httpx import AsyncClient


async def test_login_rate_limited_after_threshold(client: AsyncClient) -> None:
    # Endpoint is decorated with @limiter.limit("10/minute"). Burst 12 to
    # exhaust the bucket — credentials don't need to be valid; the limiter
    # fires before authentication.
    payload = {"email": "rl@lumen.test", "password": "anything"}
    last = None
    for _ in range(12):
        last = await client.post("/api/v1/auth/login", json=payload)
    assert last is not None
    assert last.status_code == 429, last.text
    body = last.json()
    assert body["error"]["code"] == "rate_limited"


async def test_password_reset_request_rate_limited(client: AsyncClient) -> None:
    payload = {"email": "anyone@lumen.test"}
    last = None
    for _ in range(5):
        last = await client.post("/api/v1/auth/password-reset/request", json=payload)
    assert last is not None
    assert last.status_code == 429


async def test_rate_limiter_resets_between_tests(client: AsyncClient) -> None:
    """If the autouse fixture works, this should pass cleanly even after the previous tests
    exhausted their buckets."""
    r = await client.post(
        "/api/v1/auth/login", json={"email": "fresh@lumen.test", "password": "anything"}
    )
    assert r.status_code != 429
