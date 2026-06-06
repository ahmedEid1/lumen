"""S2.11 — publish/unpublish/share endpoints + flag gate + PATCH-no-status.

DB-backed (runs under make test.api).
- POST /publish (draft->published) works for owner; /unpublish reverts.
- FEATURE_PRIVATE_PUBLISH_ENABLED off -> /share 404 (no leak window, R-S8′).
- flag on -> /share -> pending_review; non-owner 403; anonymous 401.
- PATCH /courses/{id} with status in body -> 422 (extra=forbid; FR-VIS-08).
- a non-owner serializing a listed course sees visibility but NOT
  moderation_state internals (FR-VIS-21); a non-listed course 404s.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.user import Role


async def _subject(db: AsyncSession):
    from app.models.course import Subject

    s = Subject(title="Prog", slug=f"prog-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _course_with_lesson(client, headers, subject_id) -> str:
    cid = (
        await client.post(
            "/api/v1/courses",
            json={"title": "P", "subject_id": subject_id, "overview": "x"},
            headers=headers,
        )
    ).json()["id"]
    m = (
        await client.post(f"/api/v1/courses/{cid}/modules", json={"title": "M"}, headers=headers)
    ).json()
    await client.post(
        f"/api/v1/courses/modules/{m['id']}/lessons",
        json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
        headers=headers,
    )
    return cid


@pytest.mark.asyncio
async def test_publish_then_unpublish(client: AsyncClient, auth_headers, db_session) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)

    pub = await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"
    assert pub.json()["visibility"] == "private"  # published-private

    unpub = await client.post(f"/api/v1/courses/{cid}/unpublish", headers=teacher)
    assert unpub.status_code == 200, unpub.text
    assert unpub.json()["status"] == "draft"
    assert unpub.json()["visibility"] == "private"


@pytest.mark.asyncio
async def test_share_404_when_flag_off(
    client: AsyncClient, auth_headers, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "feature_private_publish_enabled", False)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)

    r = await client.post(f"/api/v1/courses/{cid}/share", headers=teacher)
    assert r.status_code == 404  # sharing axis hidden while flag OFF (R-S8′)


@pytest.mark.asyncio
async def test_share_pending_when_flag_on(
    client: AsyncClient, auth_headers, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "feature_private_publish_enabled", True)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)

    r = await client.post(f"/api/v1/courses/{cid}/share", headers=teacher)
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "public"
    assert r.json()["moderation_state"] == "pending_review"

    # non-owner cannot share
    other = await auth_headers(role=Role.instructor)
    r2 = await client.post(f"/api/v1/courses/{cid}/share", headers=other)
    assert r2.status_code in (403, 404)

    # anonymous cannot share
    client.cookies.clear()
    r3 = await client.post(f"/api/v1/courses/{cid}/share")
    assert r3.status_code == 401


@pytest.mark.asyncio
async def test_patch_with_status_is_rejected(client: AsyncClient, auth_headers, db_session) -> None:
    """FR-VIS-08: PATCH no longer publishes — a status field 422s (extra=forbid)."""
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)

    r = await client.patch(
        f"/api/v1/courses/{cid}",
        json={"status": "published"},
        headers=teacher,
    )
    assert r.status_code == 422
    # the course did NOT publish
    detail = (await client.get(f"/api/v1/courses/{cid}", headers=teacher)).json()
    assert detail["status"] == "draft"


@pytest.mark.asyncio
async def test_non_owner_redaction(
    client: AsyncClient, auth_headers, db_session, monkeypatch
) -> None:
    """FR-VIS-21: a non-owner sees visibility but NOT moderation_state internals
    on a listed course; a non-listed course 404s."""
    monkeypatch.setattr(get_settings(), "feature_private_publish_enabled", True)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)
    await client.post(f"/api/v1/courses/{cid}/share", headers=teacher)
    # admin-approve to make it listed (set state directly — approve is S6)
    from sqlalchemy import update

    from app.models.course import Course, ModerationState

    await db_session.execute(
        update(Course).where(Course.id == cid).values(moderation_state=ModerationState.approved)
    )
    await db_session.commit()

    stranger = await auth_headers(role=Role.student)
    listed = await client.get(f"/api/v1/courses/{cid}", headers=stranger)
    assert listed.status_code == 200
    body = listed.json()
    assert body["visibility"] == "public"
    assert body["moderation_state"] is None  # redacted for non-owner (FR-VIS-21)

    # the owner sees the internal moderation_state
    owner_view = await client.get(f"/api/v1/courses/{cid}", headers=teacher)
    assert owner_view.json()["moderation_state"] == "approved"
