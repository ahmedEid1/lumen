"""Health probes."""

from __future__ import annotations

from httpx import AsyncClient


async def test_live(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_ready_db(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/ready")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "checks" in body and "db" in body["checks"]
