"""Catalog reads carry Cache-Control hints.

The public catalog endpoints previously returned no cache headers.
Every catalog hit (homepage, subject browsing, course search) went
to the database, even via a CDN or reverse proxy. ``Cache-Control:
public, max-age=60, stale-while-revalidate=300`` for anonymous reads
absorbs a thundering herd; authenticated reads stay ``private,
no-store`` so a Bearer'd body never lingers in a shared cache.

These tests don't try to verify *that* a CDN would cache — that's
the CDN's job — they just pin the header contract so a future
refactor doesn't silently drop the hint.
"""

from __future__ import annotations

from httpx import AsyncClient

_PUBLIC = "public, max-age=60, stale-while-revalidate=300"
_PRIVATE = "private, max-age=0, no-store"


async def test_subjects_carries_public_cache_for_anonymous(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/subjects")
    assert r.status_code == 200
    assert r.headers["cache-control"] == _PUBLIC
    assert "Authorization" in r.headers["vary"]


async def test_tags_carries_public_cache_for_anonymous(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/tags")
    assert r.status_code == 200
    assert r.headers["cache-control"] == _PUBLIC


async def test_courses_list_public_for_anon_private_for_auth(
    client: AsyncClient, auth_headers
) -> None:
    anon = await client.get("/api/v1/courses")
    assert anon.status_code == 200
    assert anon.headers["cache-control"] == _PUBLIC

    h = await auth_headers()
    authed = await client.get("/api/v1/courses", headers=h)
    assert authed.status_code == 200
    # An authenticated body must NEVER linger in a shared cache —
    # could leak to the next anonymous request with the same URL.
    assert authed.headers["cache-control"] == _PRIVATE
