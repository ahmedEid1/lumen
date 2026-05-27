"""Public runtime-flags endpoint (L20.5).

The endpoint is anon-readable on purpose — the frontend reads it before
sign-in to decide which features to mount. L20.5 ships only the wire
shape (defaults from Settings); L21-Sec adds a Redis override layer.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_runtime_flags_returns_default_off(client: AsyncClient) -> None:
    r = await client.get("/api/v1/runtime-flags")
    assert r.status_code == 200
    body = r.json()
    # The flag exists in the response shape — the contract.
    assert "tutor_streaming" in body
    # Default-off per Settings.feature_tutor_streaming default. Will flip
    # to True at L21b once the frontend renderer is live in prod.
    assert body["tutor_streaming"] is False


async def test_runtime_flags_is_anon_readable(client: AsyncClient) -> None:
    """No Authorization / cookie / CSRF — the endpoint stays open.

    This is a deliberate contract, not an oversight: gating it on auth
    forces the public landing page to know the user's session before it
    can decide which code path to mount, which doubles request latency
    for every cold visitor on a t4g.small.
    """
    r = await client.get("/api/v1/runtime-flags")
    assert r.status_code == 200, r.text
