"""Regression: deleting a tag that's still attached to courses must 409.

Before iteration 42 ``DELETE /admin/tags/{id}`` issued a raw
``db.delete(tag)``. The ``course_tags`` join has
``ON DELETE CASCADE`` on ``tag_id``, so the operation silently
stripped the tag from every course using it — no warning, no audit
trail of what got detached. ``DELETE /admin/subjects/{id}`` had been
hardened in iteration 28 to refuse with a 409 in the same situation;
this iteration brings tag-delete in line.

Soft-deleted courses don't block tag delete: their join rows can
cascade-away without any user-visible impact, and the admin
shouldn't need to undelete a course just to retire a tag.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject, Tag
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _make_tag(db: AsyncSession, slug: str) -> Tag:
    t = Tag(name=slug.title(), slug=f"{slug}-{uuid.uuid4().hex[:6]}")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def test_delete_tag_attached_to_live_course_is_409(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    tag = await _make_tag(db_session, "in-use")

    create = await client.post(
        "/api/v1/courses",
        json={
            "title": "Anchored",
            "subject_id": subject.id,
            "overview": "x",
            "tag_ids": [tag.id],
        },
        headers=teacher,
    )
    assert create.status_code == 201, create.text
    assert any(t["id"] == tag.id for t in create.json()["tags"])

    r = await client.delete(f"/api/v1/admin/tags/{tag.id}", headers=admin)
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["error"]["code"] == "tag.in_use"
    assert body["error"]["details"]["courses"] >= 1

    # And the course still has the tag (the failed delete didn't half-apply).
    detail = await client.get(f"/api/v1/courses/{create.json()['id']}")
    assert any(t["id"] == tag.id for t in detail.json()["tags"])


async def test_soft_deleted_course_does_not_block_tag_delete(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    tag = await _make_tag(db_session, "cleanable")

    create = await client.post(
        "/api/v1/courses",
        json={
            "title": "Going",
            "subject_id": subject.id,
            "overview": "x",
            "tag_ids": [tag.id],
        },
        headers=teacher,
    )
    course_id = create.json()["id"]
    # Soft-delete the only course using this tag.
    soft_del = await client.delete(f"/api/v1/courses/{course_id}", headers=teacher)
    assert soft_del.status_code == 200

    r = await client.delete(f"/api/v1/admin/tags/{tag.id}", headers=admin)
    assert r.status_code == 200, r.text


async def test_delete_unused_tag_succeeds(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    admin = await auth_headers(role=Role.admin)
    tag = await _make_tag(db_session, "lone")
    r = await client.delete(f"/api/v1/admin/tags/{tag.id}", headers=admin)
    assert r.status_code == 200


async def test_delete_unknown_tag_is_404(client: AsyncClient, auth_headers) -> None:
    admin = await auth_headers(role=Role.admin)
    r = await client.delete("/api/v1/admin/tags/nope", headers=admin)
    assert r.status_code == 404


async def test_delete_tag_requires_admin(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    # The endpoint is admin-only; mirror that here so a future ACL change
    # doesn't silently widen.
    teacher = await auth_headers(role=Role.instructor)
    tag = await _make_tag(db_session, "guarded")
    r = await client.delete(f"/api/v1/admin/tags/{tag.id}", headers=teacher)
    assert r.status_code in (401, 403)
