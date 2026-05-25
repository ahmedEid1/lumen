"""Regression: the upload allow-list cannot let HTML/SVG/JS through.

Before iteration 38 the ``attachment`` kind set was ``{"*"}`` — a
literal wildcard. Any authenticated user could PUT ``text/html`` or
``image/svg+xml`` content to the public bucket via a presigned URL,
and S3 would happily serve it back at the requested Content-Type. The
bucket is on the platform's own DNS, so an XSS / phishing page
hosted there inherits whatever trust the bucket domain carries
(SSO cookies, link-preview unfurls, "this is a real platform asset"
optics).

Two layers in the fix:

1. ``attachment`` now has an enumerated allow-list (docs, archives,
   media), no wildcard. Any future kind that wildcards would re-open
   the hole, so:

2. ``ALWAYS_DENIED_TYPES`` is an unconditional deny applied before the
   per-kind allow-list check. Even if someone later relaxes a kind's
   allow-list (or someone forgets to filter ``"*"`` again), the deny
   set catches the highest-risk types.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.uploads import ALLOWED_PER_KIND, ALWAYS_DENIED_TYPES


def test_no_kind_uses_wildcard():
    for kind, allowed in ALLOWED_PER_KIND.items():
        assert "*" not in allowed, f"kind={kind!r} re-introduced a wildcard"


def test_no_kind_allow_list_contains_a_denied_type():
    for kind, allowed in ALLOWED_PER_KIND.items():
        offenders = allowed & ALWAYS_DENIED_TYPES
        assert not offenders, f"kind={kind!r} allow-list contains denied types: {offenders!r}"


def test_always_denied_covers_the_classic_xss_carriers():
    must_have = {
        "text/html",
        "image/svg+xml",
        "application/javascript",
        "text/javascript",
    }
    missing = must_have - ALWAYS_DENIED_TYPES
    assert not missing, f"deny-set missing: {missing!r}"


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "image/svg+xml",
        "application/javascript",
        "text/javascript",
        "application/x-javascript",
    ],
)
async def test_sign_rejects_xss_carriers_for_attachment_kind(
    content_type: str, client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "evil.bin",
            "content_type": content_type,
            "kind": "attachment",
            "size_bytes": 1024,
        },
        headers=h,
    )
    assert r.status_code == 422, r.text
    # Either the deny-set or the per-kind allow-list rejects it;
    # both codes are acceptable proof the upload was blocked.
    assert r.json()["error"]["code"] in {
        "upload.content_type_denied",
        "upload.content_type",
    }


async def test_sign_allows_a_typical_attachment(client: AsyncClient, auth_headers) -> None:
    h = await auth_headers()
    r = await client.post(
        "/api/v1/uploads/sign",
        json={
            "filename": "homework.pdf",
            "content_type": "application/pdf",
            "kind": "attachment",
            "size_bytes": 200_000,
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"].startswith("attachment/")
    # POST presign — Content-Type lives in the signed
    # ``fields`` dict; the client must POST it as a form field so S3
    # can compare it against the policy condition.
    assert body["fields"]["Content-Type"] == "application/pdf"
    # And the server-enforced max_bytes is exposed for the UI.
    assert body["max_bytes"] >= 100_000
