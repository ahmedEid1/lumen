"""Cookie-authenticated mutating requests must come from a trusted origin.

SameSite=strict on our auth cookies already stops modern browsers from
sending them on truly cross-site requests, so the gap this middleware
closes is narrow: a same-site origin compromise (subdomain takeover),
an older browser without modern SameSite support, or a regression that
weakens the cookie policy. The explicit Origin check makes those
scenarios fail safely.

Bearer-token clients (mobile / Postman / server-to-server) skip the
check because they had to actively set ``Authorization``; the attacker
can't do that cross-origin without explicit user action.
"""

from __future__ import annotations

from httpx import AsyncClient


async def _login_set_cookie(client: AsyncClient, make_user) -> str:
    user = await make_user(email="csrf@lumen.test", password="Password!1234")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password!1234"},
    )
    assert r.status_code == 200
    # access cookie name varies by env; test uses non-prod so it's just "access"
    cookie = r.cookies.get("access") or r.cookies.get("__Host-access")
    assert cookie is not None
    return cookie


async def test_cookie_post_without_origin_is_rejected(
    client: AsyncClient, make_user
) -> None:
    cookie = await _login_set_cookie(client, make_user)
    # Iter 110: conftest sets a default `Origin: http://testserver`
    # so most tests don't trip CSRF. Pop it for this one so the
    # no-Origin rejection path is the one we exercise.
    client.headers.pop("Origin", None)
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        cookies={"access": cookie},
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "csrf.bad_origin"


async def test_cookie_post_with_untrusted_origin_is_rejected(
    client: AsyncClient, make_user
) -> None:
    cookie = await _login_set_cookie(client, make_user)
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        cookies={"access": cookie},
        headers={"Origin": "https://attacker.example"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf.bad_origin"


async def test_cookie_post_with_trusted_origin_passes(
    client: AsyncClient, make_user
) -> None:
    cookie = await _login_set_cookie(client, make_user)
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        cookies={"access": cookie},
        # Default CORS origin in test env is http://localhost:3000.
        headers={"Origin": "http://localhost:3000"},
    )
    # Either succeeds (change went through) or fails for some other
    # reason — what matters is it's NOT the CSRF rejection.
    assert r.status_code != 403 or r.json()["error"]["code"] != "csrf.bad_origin"


async def test_bearer_post_without_origin_passes(
    client: AsyncClient, auth_headers
) -> None:
    """Bearer-token requests skip the CSRF check entirely — no cookie,
    no CSRF surface. This matches how mobile / Postman / SDKs use the API."""
    h = await auth_headers()
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        headers=h,
    )
    assert r.status_code == 200, r.text


async def test_get_with_cookie_is_not_csrf_checked(
    client: AsyncClient, make_user
) -> None:
    """Read methods can't mutate state, so the check only applies to
    POST/PUT/PATCH/DELETE. A GET with the cookie and a bad Origin
    must still succeed."""
    cookie = await _login_set_cookie(client, make_user)
    r = await client.get(
        "/api/v1/auth/me",
        cookies={"access": cookie},
        headers={"Origin": "https://attacker.example"},
    )
    assert r.status_code == 200


async def test_referer_fallback_when_origin_missing(
    client: AsyncClient, make_user
) -> None:
    """Some browsers omit Origin on same-origin POSTs; the middleware
    falls back to the Referer's scheme://host."""
    cookie = await _login_set_cookie(client, make_user)
    # Iter 110: pop the conftest default Origin so the Referer-
    # fallback path is the one exercised.
    client.headers.pop("Origin", None)
    r = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "Password!1234", "new_password": "NewPassword!1234"},
        cookies={"access": cookie},
        headers={"Referer": "http://localhost:3000/settings"},
    )
    assert r.status_code != 403 or r.json()["error"]["code"] != "csrf.bad_origin"
