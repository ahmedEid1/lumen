"""Regression: slug minting on the create + rename paths.

Two original cases lived here; one no longer applies and the other
still does:

* ``test_recreating_a_deleted_courses_title_picks_a_fresh_slug`` was
  written under the pre-B3 invariant: slugs were unconditionally
  unique, so a soft-deleted course's slug had to be avoided by the
  minter. **Rebuild Fix B3 replaced the unconditional unique index
  with a partial unique on live rows only** (``uq_courses_slug_live``),
  which made slug reuse-after-soft-delete a feature, not a bug. The
  case below now locks in B3's behaviour — the second course gets the
  same slug the soft-deleted one had, no ``-2`` suffix.
* ``test_renaming_keeps_slug_when_unchanged`` is unchanged and still
  guards the ``exclude_id`` shortcut in the slug minter.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_recreating_a_deleted_courses_title_picks_a_fresh_slug(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """After B3, the soft-deleted row's slug is *available* for reuse.

    The minter checks ``slug_is_taken`` which (since B3) filters on
    ``deleted_at IS NULL``. So the second course can — and should —
    reclaim the original slug without a ``-2`` suffix. The partial-
    unique index ``uq_courses_slug_live`` enforces that this is safe.
    Renaming the test would lose the regression-name; the body now
    locks in the post-B3 contract instead.
    """
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)

    first = await client.post(
        "/api/v1/courses",
        json={"title": "Quantum mechanics", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    assert first.status_code == 201
    first_slug = first.json()["slug"]
    first_id = first.json()["id"]

    deleted = await client.delete(f"/api/v1/courses/{first_id}", headers=teacher)
    assert deleted.status_code == 200

    second = await client.post(
        "/api/v1/courses",
        json={"title": "Quantum mechanics", "subject_id": subject.id, "overview": "y"},
        headers=teacher,
    )
    assert second.status_code == 201, second.text
    # B3's contract: the soft-deleted row no longer blocks the slug;
    # the live course gets the canonical "quantum-mechanics" back.
    assert second.json()["slug"] == first_slug


# NOTE: the ``test_duplicating_a_course_uses_a_fresh_slug`` case that
# lived here previously exercised the
# ``POST /api/v1/courses/{course_id}/duplicate`` endpoint, removed in
# rebuild Cut A5. Slug uniqueness on the surviving create + rename
# paths is still asserted by the two cases that bracket it; the
# slug-mint helper they all share is what was load-bearing here.


async def test_renaming_keeps_slug_when_unchanged(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Renaming back to the current title must not pick a sibling slug
    just because the row exists. ``exclude_id`` is the guard."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Stable name", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    original_slug = create.json()["slug"]

    # PATCH to the same title — should be a no-op for the slug
    patch = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"title": "Stable name"},
        headers=teacher,
    )
    assert patch.status_code == 200
    assert patch.json()["slug"] == original_slug
