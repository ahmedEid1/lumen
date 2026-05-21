"""Catalog endpoints: subjects, tags, and the searchable course list."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import DBSession, OptionalUser
from app.api.v1 import _builders
from app.repositories import courses as courses_repo
from app.schemas.common import Page
from app.schemas.course import CourseListItem, SubjectOut, TagOut

router = APIRouter()

# Cache hint applied to the unauthenticated catalog reads. ``public``
# lets any CDN / reverse proxy cache; ``max-age=60`` is small enough
# that a course publish takes ~1 min to propagate to the homepage,
# big enough to absorb a thundering herd. Authenticated callers add
# ``Vary: Authorization`` so a Bearer'd request can't be served the
# anonymous cached body (the response body itself doesn't currently
# differ by auth, but stating Vary now keeps us safe if it ever does).
_PUBLIC_LIST_CACHE = "public, max-age=60, stale-while-revalidate=300"


def _apply_public_cache(response: Response, viewer_present: bool) -> None:
    if viewer_present:
        # Per-caller hints. Don't put authenticated bodies in shared caches.
        response.headers["Cache-Control"] = "private, max-age=0, no-store"
    else:
        response.headers["Cache-Control"] = _PUBLIC_LIST_CACHE
        response.headers["Vary"] = "Accept-Encoding, Authorization"


@router.get("/subjects", response_model=list[SubjectOut])
async def list_subjects(db: DBSession, response: Response) -> list[SubjectOut]:
    # Subjects rarely change; happy to serve a minute-old copy from a
    # CDN. No per-viewer fields, so no Vary on Cookie/Authorization
    # beyond the defensive Authorization marker.
    _apply_public_cache(response, viewer_present=False)
    rows = await courses_repo.list_subjects(db)
    return [SubjectOut(id=s.id, title=s.title, slug=s.slug, total_courses=n) for s, n in rows]


@router.get("/tags", response_model=list[TagOut])
async def list_tags(db: DBSession, response: Response) -> list[TagOut]:
    _apply_public_cache(response, viewer_present=False)
    rows = await courses_repo.list_tags(db)
    return [TagOut.model_validate(t) for t in rows]


@router.get("/courses", response_model=Page[CourseListItem])
async def list_courses(
    db: DBSession,
    viewer: OptionalUser,
    response: Response,
    q: Annotated[str | None, Query(max_length=200)] = None,
    subject: Annotated[str | None, Query(max_length=140)] = None,
    tag: Annotated[str | None, Query(max_length=80)] = None,
    difficulty: Annotated[str | None, Query(max_length=20)] = None,
    sort: Annotated[str, Query(max_length=40)] = "-created_at",
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[CourseListItem]:
    # Catalog list is identical for anonymous and authenticated callers
    # today, but we still split the cache hints — an authenticated
    # response that lingers in a shared CDN would leak to the next
    # anonymous user with the same query string.
    _apply_public_cache(response, viewer_present=viewer is not None)
    courses, total = await courses_repo.search_courses(
        db,
        q=q,
        subject_slug=subject,
        tag_slug=tag,
        difficulty=difficulty,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    stats = await courses_repo.stats_for_courses(db, [c.id for c in courses])
    items = [_builders.list_item(c, stats.get(c.id, {})) for c in courses]
    return Page(items=items, total=total, page=page, page_size=page_size)
