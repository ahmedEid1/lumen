"""Idempotency-Key middleware: replay on same body, conflict on diff.

CLAUDE.md flagged Idempotency-Key support as planned in v1. It is
wired in as opt-in via the ``Idempotency-Key`` header on mutating
methods. Behaviour matches the draft RFC:

* same key + same body within TTL → cached response replayed (with
  an ``Idempotent-Replayed: true`` marker header so observability
  doesn't mistake the burst for a bug);
* same key + different body → 422 ``idempotency.conflict``;
* missing key → middleware is a no-op.

These tests don't exercise the Redis TTL — that's a configuration
constant rather than a behavioural property — and they don't try to
test the "Redis is down" fail-open path, which is logged but
intentionally silent so a transient outage doesn't lock users out
mid-form-submit.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_replay_returns_cached_response(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    key = f"idemp-{uuid.uuid4().hex}"
    body = {"current_password": "Password!1234", "new_password": "NewPassword!1234"}
    first = await client.post(
        "/api/v1/users/me/change-password",
        json=body,
        headers={**h, "Idempotency-Key": key},
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/users/me/change-password",
        json=body,
        headers={**h, "Idempotency-Key": key},
    )
    assert second.status_code == 200
    assert second.json() == first.json()
    # Replay marker so callers / dashboards can distinguish cached
    # responses from re-executed ones.
    assert second.headers.get("idempotent-replayed") == "true"


async def test_replay_with_different_body_returns_conflict(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    key = f"idemp-{uuid.uuid4().hex}"
    first = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        headers={**h, "Idempotency-Key": key},
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "different", "new_password": "DifferentPwd!42"},
        headers={**h, "Idempotency-Key": key},
    )
    assert second.status_code == 422, second.text
    assert second.json()["error"]["code"] == "idempotency.conflict"


async def test_no_key_is_passthrough(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.headers.get("idempotent-replayed") != "true"


async def test_get_request_ignores_key(
    client: AsyncClient, auth_headers
) -> None:
    """Read methods are naturally idempotent — the middleware shouldn't
    waste a Redis round-trip on them."""
    h = await auth_headers()
    r = await client.get(
        "/api/v1/auth/me",
        headers={**h, "Idempotency-Key": "noop"},
    )
    assert r.status_code == 200
    assert r.headers.get("idempotent-replayed") != "true"


async def test_failed_response_is_not_cached(
    client: AsyncClient, auth_headers
) -> None:
    """A 4xx shouldn't be pinned — the caller should be able to fix
    their input and retry with the same key. We only cache 2xx."""
    h = await auth_headers()
    key = f"idemp-{uuid.uuid4().hex}"
    # Wrong current password → 401
    bad = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "wrong", "new_password": "NewPassword!1234"},
        headers={**h, "Idempotency-Key": key},
    )
    assert bad.status_code == 401
    # Retry with the right credentials and the same key — must NOT
    # be the cached 401; must execute normally.
    good = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        headers={**h, "Idempotency-Key": key},
    )
    # Same key, different body → would be 422 idempotency.conflict
    # *if we cached the 401*. The cache-only-on-2xx rule means we
    # didn't, so this runs fresh.
    assert good.status_code == 200


async def test_oversized_key_rejected(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    long_key = "x" * 500
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        headers={**h, "Idempotency-Key": long_key},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "idempotency.bad_key"
