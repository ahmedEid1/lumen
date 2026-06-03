"""Gate-C — archive/restore lifecycle endpoints (ADR-0026 §4).

S2 shipped the *→archived and archived→draft transitions in
``_transition_status`` but removed the only lever (PATCH {status}) without
adding endpoints, so ``archived`` was unreachable. These cover the new
POST /courses/{id}/archive and /restore (lifecycle, NO feature flag):

- owner archives a published course -> status=archived + visibility=private
  (force-private + unfeature on archive, like unpublish — ADR-0026 §4);
- restore (archived->draft) works for the owner;
- archive is the ONLY way *into* archived; archived->draft is the only way out;
- non-owner gets 403; anonymous gets 401;
- an archived course is NOT in the public catalog (is_publicly_listed false);
- an enrolled learner keeps access after archive (grandfathering, R-VIS-13).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_archive_published_then_restore(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)

    arch = await client.post(f"/api/v1/courses/{cid}/archive", headers=teacher)
    assert arch.status_code == 200, arch.text
    assert arch.json()["status"] == "archived"
    # Archive force-privates (and unfeatures) — ADR-0026 §4 atomic side-effect.
    assert arch.json()["visibility"] == "private"

    restore = await client.post(f"/api/v1/courses/{cid}/restore", headers=teacher)
    assert restore.status_code == 200, restore.text
    # archived -> draft is the only legal exit from archived.
    assert restore.json()["status"] == "draft"
    assert restore.json()["visibility"] == "private"


@pytest.mark.asyncio
async def test_archive_no_feature_flag_required(
    client: AsyncClient, auth_headers, db_session, monkeypatch
) -> None:
    """Archive is lifecycle, not sharing — it works even with the private-publish
    sharing flag OFF (unlike /share which 404s while the flag is off)."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "feature_private_publish_enabled", False)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)

    arch = await client.post(f"/api/v1/courses/{cid}/archive", headers=teacher)
    assert arch.status_code == 200, arch.text
    assert arch.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_archive_non_owner_forbidden(client: AsyncClient, auth_headers, db_session) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)

    other = await auth_headers(role=Role.instructor)
    r = await client.post(f"/api/v1/courses/{cid}/archive", headers=other)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "course.forbidden"


@pytest.mark.asyncio
async def test_archive_anonymous_unauthorized(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)

    client.cookies.clear()
    r = await client.post(f"/api/v1/courses/{cid}/archive")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_restore_non_owner_forbidden(client: AsyncClient, auth_headers, db_session) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)
    await client.post(f"/api/v1/courses/{cid}/archive", headers=teacher)

    other = await auth_headers(role=Role.instructor)
    r = await client.post(f"/api/v1/courses/{cid}/restore", headers=other)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_archived_course_not_in_catalog(
    client: AsyncClient, auth_headers, db_session, monkeypatch
) -> None:
    """An archived course can never be publicly listed — archive force-privates,
    and the catalog is filtered by publicly_listed_sql (visibility=public AND
    status=published AND moderation_state=approved). Even a course that was
    public+approved must drop out of the catalog once archived."""
    from sqlalchemy import update

    from app.core.config import get_settings
    from app.models.course import Course, ModerationState

    monkeypatch.setattr(get_settings(), "feature_private_publish_enabled", True)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)
    await client.post(f"/api/v1/courses/{cid}/share", headers=teacher)
    # Admin-approve directly (approve is S6) so the course is genuinely listed.
    await db_session.execute(
        update(Course).where(Course.id == cid).values(moderation_state=ModerationState.approved)
    )
    await db_session.commit()

    # Listed before archive.
    listed = await client.get("/api/v1/courses", params={"subject": subject.slug})
    assert cid in {item["id"] for item in listed.json()["items"]}

    # Archive drops it out of the catalog (force-private breaks is_publicly_listed).
    arch = await client.post(f"/api/v1/courses/{cid}/archive", headers=teacher)
    assert arch.status_code == 200, arch.text
    assert arch.json()["status"] == "archived"
    assert arch.json()["visibility"] == "private"

    after = await client.get("/api/v1/courses", params={"subject": subject.slug})
    assert cid not in {item["id"] for item in after.json()["items"]}


@pytest.mark.asyncio
async def test_enrolled_learner_retains_access_after_archive(
    client: AsyncClient, auth_headers, db_session, monkeypatch
) -> None:
    """R-VIS-13 grandfathering: a learner enrolled while the course was listed
    keeps detail access after the owner archives it (can_view_course's
    enrollment branch), even though the course is no longer publicly listed."""
    from sqlalchemy import update

    from app.core.config import get_settings
    from app.models.course import Course, ModerationState

    monkeypatch.setattr(get_settings(), "feature_private_publish_enabled", True)
    teacher = await auth_headers(role=Role.instructor)
    subject = await _subject(db_session)
    cid = await _course_with_lesson(client, teacher, subject.id)
    await client.post(f"/api/v1/courses/{cid}/publish", headers=teacher)
    await client.post(f"/api/v1/courses/{cid}/share", headers=teacher)
    await db_session.execute(
        update(Course).where(Course.id == cid).values(moderation_state=ModerationState.approved)
    )
    await db_session.commit()

    # Learner enrolls while the course is listed.
    learner = await auth_headers(role=Role.student)
    enr = await client.post(f"/api/v1/me/enrollments/{cid}", headers=learner)
    assert enr.status_code == 201, enr.text

    # Owner archives.
    arch = await client.post(f"/api/v1/courses/{cid}/archive", headers=teacher)
    assert arch.status_code == 200, arch.text

    # The grandfathered learner still sees the (now-archived, private) course.
    seen = await client.get(f"/api/v1/courses/{cid}", headers=learner)
    assert seen.status_code == 200, seen.text
    assert seen.json()["status"] == "archived"

    # A stranger with no enrollment gets the existence-hiding 404.
    stranger = await auth_headers(role=Role.student)
    miss = await client.get(f"/api/v1/courses/{cid}", headers=stranger)
    assert miss.status_code == 404, miss.text
