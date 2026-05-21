"""Course CRUD + publishing + ordering + enrollment + progress."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject, Tag
from app.models.user import Role


async def _make_subject(db: AsyncSession, slug: str = "programming") -> Subject:
    s = Subject(title="Programming", slug=f"{slug}-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _instructor_login(client: AsyncClient, auth_headers) -> dict[str, str]:
    return await auth_headers(role=Role.instructor)


async def test_only_instructors_can_create_courses(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    student = await auth_headers(role=Role.student)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Bad", "subject_id": subject.id},
        headers=student,
    )
    assert r.status_code == 403


async def test_instructor_creates_course_with_unique_slug(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    headers = await _instructor_login(client, auth_headers)
    r1 = await client.post(
        "/api/v1/courses",
        json={
            "title": "FastAPI Crash Course",
            "subject_id": subject.id,
            "overview": "Build a tiny API.",
        },
        headers=headers,
    )
    assert r1.status_code == 201, r1.text
    body1 = r1.json()
    assert body1["status"] == "draft"
    assert body1["slug"]

    r2 = await client.post(
        "/api/v1/courses",
        json={"title": "FastAPI Crash Course", "subject_id": subject.id, "overview": "x"},
        headers=headers,
    )
    assert r2.status_code == 201
    assert r2.json()["slug"] != body1["slug"]


async def test_publish_and_list_in_catalog(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    headers = await _instructor_login(client, auth_headers)

    r = await client.post(
        "/api/v1/courses",
        json={"title": "Async Python", "subject_id": subject.id, "overview": "Coroutines & tasks."},
        headers=headers,
    )
    course_id = r.json()["id"]

    pub = await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=headers,
    )
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"
    assert pub.json()["published_at"] is not None

    catalog = await client.get("/api/v1/courses?page=1&page_size=20")
    assert catalog.status_code == 200
    ids = [c["id"] for c in catalog.json()["items"]]
    assert course_id in ids


async def test_modules_lessons_and_reorder(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    headers = await _instructor_login(client, auth_headers)

    r = await client.post(
        "/api/v1/courses",
        json={"title": "Course", "subject_id": subject.id, "overview": "x"},
        headers=headers,
    )
    course_id = r.json()["id"]

    m1 = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "Intro"}, headers=headers
        )
    ).json()
    m2 = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "Deeper"}, headers=headers
        )
    ).json()
    assert m1["order"] == 0 and m2["order"] == 1

    # Reorder
    rr = await client.post(
        f"/api/v1/courses/{course_id}/modules/order",
        json={"order": {m1["id"]: 1, m2["id"]: 0}},
        headers=headers,
    )
    assert rr.status_code == 200, rr.text

    # Add a text lesson
    lesson = await client.post(
        f"/api/v1/courses/modules/{m1['id']}/lessons",
        json={
            "title": "Hello",
            "type": "text",
            "data": {"type": "text", "body_markdown": "# Hi"},
        },
        headers=headers,
    )
    assert lesson.status_code == 201, lesson.text


async def test_enrollment_and_progress(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Enroll Me", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]

    # Module + lesson
    m = (await client.post(f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher)).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()

    pub = await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)
    assert pub.status_code == 200

    # Enroll
    enroll = await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    assert enroll.status_code == 201, enroll.text
    assert enroll.json()["progress_pct"] == 0

    # Mark complete
    progress = await client.post(
        f"/api/v1/me/progress/lessons/{lesson['id']}",
        json={"completed": True},
        headers=student,
    )
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert body["progress_pct"] == 100.0
    assert body["certificate_id"] is not None


async def test_review_requires_enrollment(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)

    create = await client.post(
        "/api/v1/courses",
        json={"title": "Need Enroll", "subject_id": subject.id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    await client.patch(f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher)

    r_fail = await client.put(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 5, "body": "Loved it"},
        headers=student,
    )
    assert r_fail.status_code == 403
    assert r_fail.json()["error"]["code"] == "review.enroll_first"

    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    r_ok = await client.put(
        f"/api/v1/courses/{course_id}/reviews",
        json={"rating": 4, "body": "Solid."},
        headers=student,
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["rating"] == 4
