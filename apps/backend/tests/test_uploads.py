"""Upload signing — validates input, content-type allow-list, size limits."""

from __future__ import annotations

from httpx import AsyncClient


async def test_sign_requires_auth(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "a.png",
            "content_type": "image/png",
            "kind": "avatar",
            "size_bytes": 1024,
        },
    )
    assert r.status_code == 401


async def test_sign_rejects_disallowed_content_type(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "bad.exe",
            "content_type": "application/x-msdownload",
            "kind": "avatar",
            "size_bytes": 1024,
        },
        headers=h,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "upload.content_type"


async def test_sign_rejects_oversized(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "huge.png",
            "content_type": "image/png",
            "kind": "avatar",
            "size_bytes": 100 * 1024 * 1024,
        },
        headers=h,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "upload.too_large"


async def test_sign_rejects_unknown_kind(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "a.png",
            "content_type": "image/png",
            "kind": "wrong",
            "size_bytes": 1024,
        },
        headers=h,
    )
    # `kind` is constrained by the schema, so it should be 422 from Pydantic
    assert r.status_code == 422
