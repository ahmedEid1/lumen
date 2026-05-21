"""Regression: every API response carries the defense-in-depth headers.

The API serves JSON to the Next.js frontend. The only HTML it produces
is Swagger UI at ``/docs`` and the trivial ``/`` welcome. None of
these legitimately need to be framed, MIME-sniffed, or referer-leaked
to third-party origins, so the SecurityHeadersMiddleware pins:

* ``X-Content-Type-Options: nosniff`` — kill the IE/Safari MIME-sniff
  attack class outright
* ``X-Frame-Options: DENY`` — no embedding the API into a hostile
  iframe (clickjacking)
* ``Referrer-Policy: strict-origin-when-cross-origin`` — keep paths
  and query strings out of cross-origin Referer
* ``Permissions-Policy: ...`` — the API origin never needs camera /
  mic / geolocation / payment / usb, so lock them
* ``Cross-Origin-Resource-Policy: same-site`` — leaked URLs cannot
  be hot-linked into unrelated origins
* ``Strict-Transport-Security`` (prod only) — defense in depth behind
  Caddy in case the API is ever briefly exposed directly

These tests pin the headers across a public endpoint, an auth-gated
endpoint, an error response, and the docs HTML page so a future change
that bypasses the middleware fails loudly.
"""

from __future__ import annotations

from httpx import AsyncClient

_EXPECTED_DEFAULTS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def _assert_security_headers(response) -> None:
    h = {k.lower(): v for k, v in response.headers.items()}
    for key, expected in _EXPECTED_DEFAULTS.items():
        assert h.get(key) == expected, f"{key}: got {h.get(key)!r}, want {expected!r}"
    # Permissions-Policy is a multi-token header — pin its presence and
    # check it locks down the four powerful features that the API
    # origin never legitimately needs.
    pp = h.get("permissions-policy", "")
    for feature in ("camera", "microphone", "geolocation", "payment"):
        assert f"{feature}=()" in pp, f"Permissions-Policy missing {feature}=(): {pp!r}"


async def test_headers_present_on_public_endpoint(client: AsyncClient) -> None:
    r = await client.get("/api/v1/subjects")
    assert r.status_code == 200
    _assert_security_headers(r)


async def test_headers_present_on_auth_endpoint(
    client: AsyncClient, auth_headers
) -> None:
    h = await auth_headers()
    r = await client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 200
    _assert_security_headers(r)


async def test_headers_present_on_error_response(client: AsyncClient) -> None:
    # 401 — still must carry security headers, otherwise an attacker
    # could iframe a "session expired" page for a clickjacking flow.
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 401
    _assert_security_headers(r)


async def test_headers_present_on_docs_html(client: AsyncClient) -> None:
    r = await client.get("/docs")
    assert r.status_code == 200
    _assert_security_headers(r)


async def test_csp_set_on_json_responses(client: AsyncClient) -> None:
    """JSON responses get a strict CSP so a browser tricked into
    rendering one as HTML can't load anything from it."""
    r = await client.get("/api/v1/subjects")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


async def test_csp_absent_on_html_docs(client: AsyncClient) -> None:
    """Swagger UI uses inline scripts + a CDN; a strict CSP would
    break it. Iter 70 gates CSP on application/json content-type."""
    r = await client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in {k.lower() for k in r.headers}


async def test_server_header_is_stripped(client: AsyncClient) -> None:
    """uvicorn defaults to advertising itself via ``Server: uvicorn``;
    a middleware strips it on the way out so attackers can't fingerprint
    the stack from a single response."""
    r = await client.get("/api/v1/subjects")
    headers_lower = {k.lower(): v for k, v in r.headers.items()}
    assert "server" not in headers_lower


async def test_hsts_only_in_production(client: AsyncClient) -> None:
    """In dev/test we serve plain HTTP on localhost; sending HSTS would
    poison a developer's browser for two years. The middleware gates
    it on ``settings.is_prod`` — verified here by *absence* in test
    env. The positive case (prod emits the header) is a single ``if``
    in main.SecurityHeadersMiddleware and inspected, not tested under
    a faked prod env (which would also fight the assert_production_ready
    boot guard)."""
    r = await client.get("/api/v1/subjects")
    assert "strict-transport-security" not in {
        k.lower() for k in r.headers
    }
