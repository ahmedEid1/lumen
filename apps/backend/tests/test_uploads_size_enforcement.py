"""Regression: presign carries an S3-enforced content-length-range.

``size_bytes`` in the presign request used to be advisory —
the server's per-kind cap was checked against the *client-claimed*
size before signing, but the resulting ``generate_presigned_url(PUT)``
embedded no length constraint. A client could lie ("size_bytes": 1024)
and PUT a 1GB file; S3 would happily accept it.

The fix switches to ``generate_presigned_post`` with
``Conditions=[["content-length-range", 1, max_bytes]]``. The cap is
now enforced *by S3 itself*, server-side, on the actual upload.

The presign response shape changed from {url, headers, ...} to
{url, fields, max_bytes, ...} — locked in here.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_presign_returns_post_method_and_fields(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "x.png",
            "content_type": "image/png",
            "kind": "avatar",
            "size_bytes": 200_000,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "POST"
    # fields must include the form values S3 expects on the upload.
    assert "Content-Type" in body["fields"]
    assert body["fields"]["Content-Type"] == "image/png"
    # max_bytes is exposed so the client can render a useful error
    # if S3 returns 403 EntityTooLarge.
    assert body["max_bytes"] == 5 * 1024 * 1024  # avatar cap


async def test_presign_max_bytes_matches_per_kind_cap(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    # Same request shape across kinds — only ``max_bytes`` should change.
    cases = {
        "avatar": 5 * 1024 * 1024,
        "cover": 10 * 1024 * 1024,
        "lesson": 1024 * 1024 * 1024,
        "attachment": 100 * 1024 * 1024,
    }
    for kind, expected in cases.items():
        r = await client.post(
            "/api/v1/uploads/sign",
            json={
                "filename": "x.png",
                "content_type": "image/png",
                "kind": kind,
                "size_bytes": 1024,
            },
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["max_bytes"] == expected, kind


async def test_presign_still_rejects_oversized_at_request_time(
    client: AsyncClient, auth_headers
) -> None:
    """The per-kind check remains as a fast pre-flight — clients that
    obviously won't fit get a 422 before we even mint a presign. S3
    enforces the same limit on the actual upload as defense in depth."""
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


async def test_presign_response_no_longer_carries_put_headers(
    client: AsyncClient, auth_headers
) -> None:
    """Iter 56 contract change: ``headers`` is gone, replaced by
    ``fields``. Pin so a future API client doesn't keep reading the
    stale key and silently send nothing."""
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "x.png",
            "content_type": "image/png",
            "kind": "avatar",
            "size_bytes": 1024,
        },
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert "headers" not in body
    assert "fields" in body
