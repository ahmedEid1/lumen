"""Free-preview lessons are visible to anyone on published courses."""

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


async def test_preview_lesson_accessible_anonymously(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Preview", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
        )
    ).json()
    preview = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Hello",
                "type": "text",
                "is_preview": True,
                "data": {"type": "text", "body_markdown": "hi"},
            },
            headers=teacher,
        )
    ).json()
    locked = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Locked",
                "type": "text",
                "data": {"type": "text", "body_markdown": "secret"},
            },
            headers=teacher,
        )
    ).json()
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )

    # clear the httpx cookie jar so "anonymous" requests
    # below aren't auto-authed by the teacher login cookie sticky
    # in the client.
    client.cookies.clear()

    # Anonymous can fetch the preview lesson
    anon_preview = await client.get(f"/api/v1/courses/lessons/{preview['id']}")
    assert anon_preview.status_code == 200
    assert anon_preview.json()["is_preview"] is True

    # Anonymous is unauthorized on the locked lesson
    anon_locked = await client.get(f"/api/v1/courses/lessons/{locked['id']}")
    assert anon_locked.status_code == 401

    # Authenticated non-enrolled gets 403 on the locked lesson
    student = await auth_headers(role=Role.student)
    locked_student = await client.get(f"/api/v1/courses/lessons/{locked['id']}", headers=student)
    assert locked_student.status_code == 403
    assert locked_student.json()["error"]["code"] == "lesson.enroll_first"


async def test_preview_hidden_on_draft_courses(
    client: AsyncClient, auth_headers, db_session
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Draft preview", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
        )
    ).json()
    preview = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Preview",
                "type": "text",
                "is_preview": True,
                "data": {"type": "text", "body_markdown": "x"},
            },
            headers=teacher,
        )
    ).json()

    # drop stale teacher login cookie before the anon GET.
    client.cookies.clear()
    # Course is draft, so preview is not public
    anon = await client.get(f"/api/v1/courses/lessons/{preview['id']}")
    assert anon.status_code == 401

    # Owner still sees it
    owner = await client.get(f"/api/v1/courses/lessons/{preview['id']}", headers=teacher)
    assert owner.status_code == 200


async def test_preview_hidden_on_published_private_course(
    client: AsyncClient, auth_headers, db_session
) -> None:
    """S2.4: a published-PRIVATE course's preview lesson must NOT leak to a
    stranger — the gate keys on is_publicly_listed, not raw status==published.
    """
    from sqlalchemy import select, update

    from app.models.course import Course, ModerationState, Visibility

    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    create = await client.post(
        "/api/v1/courses",
        json={"title": "Private preview", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
        )
    ).json()
    preview = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Preview",
                "type": "text",
                "is_preview": True,
                "data": {"type": "text", "body_markdown": "x"},
            },
            headers=teacher,
        )
    ).json()
    # Publish but keep it PRIVATE (status=published, visibility=private,
    # moderation_state=none) — the published-private self-learn state.
    await db_session.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(
            status="published",
            visibility=Visibility.private,
            moderation_state=ModerationState.none,
        )
    )
    await db_session.commit()
    # sanity: it is NOT publicly listed
    course = (await db_session.execute(select(Course).where(Course.id == course_id))).scalar_one()
    from app.services import visibility as vis

    assert vis.is_publicly_listed(course) is False

    client.cookies.clear()
    anon = await client.get(f"/api/v1/courses/lessons/{preview['id']}")
    # published-private preview is NOT anonymously readable (no leak)
    assert anon.status_code == 401

    # Owner still sees it (self-learn)
    owner = await client.get(f"/api/v1/courses/lessons/{preview['id']}", headers=teacher)
    assert owner.status_code == 200
