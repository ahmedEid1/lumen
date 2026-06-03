"""Course CRUD + publishing + ordering + enrollment + progress."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession, slug: str = "programming") -> Subject:
    s = Subject(title="Programming", slug=f"{slug}-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _instructor_login(client: AsyncClient, auth_headers) -> dict[str, str]:
    return await auth_headers(role=Role.instructor)


async def test_user_role_can_create_course(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    # S1.4 / FR-RBAC-02: course creation is ungated from the instructor role.
    # Any active user (here a `user`-role caller, formerly the `student` who
    # used to get 403 `courses.forbidden`) can now create a course.
    subject = await _make_subject(db_session)
    headers = await auth_headers(role=Role.user)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "My First Course", "subject_id": subject.id, "overview": "x"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"


async def test_user_role_can_list_my_courses(client: AsyncClient, auth_headers) -> None:
    # S1.4: `GET /courses/mine` is reachable by any active user.
    headers = await auth_headers(role=Role.user)
    r = await client.get("/api/v1/courses/mine", headers=headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


async def test_suspended_user_cannot_create_course(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    # S1.4 / FR-DEFINE-06: a suspended (is_active=False) user is denied.
    # The token mints fine (the JWT claim is inert) but the live DB row is
    # inactive — the capability layer / auth dep refuses the write. The
    # foundation's `get_current_user_optional` drops an inactive row to 401
    # `auth.required`; the capability predicate also denies (403
    # `auth.capability`). Either way the door is shut — see the merge note in
    # test_deps_capabilities.py::test_require_author_suspended_403_capability.
    import uuid

    from sqlalchemy import update

    from app.core.security import create_access_token
    from app.models.user import User

    subject = await _make_subject(db_session)
    email = f"suspended-{uuid.uuid4().hex[:8]}@lumen.test"
    user = await make_user(email=email, role=Role.user)
    await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db_session.commit()
    token, _ = create_access_token(subject=user.id, role=str(Role.user))
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Should Fail", "subject_id": subject.id, "overview": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code in (401, 403), r.text
    assert r.json()["error"]["code"] in ("auth.required", "auth.capability")


async def test_anonymous_cannot_create_course(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    subject = await _make_subject(db_session)
    r = await client.post(
        "/api/v1/courses",
        json={"title": "Anon", "subject_id": subject.id, "overview": "x"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth.required"


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
    client: AsyncClient,
    auth_headers,
    seed_lesson,
    db_session: AsyncSession,
    publish_and_list_course,
) -> None:
    subject = await _make_subject(db_session)
    headers = await _instructor_login(client, auth_headers)

    r = await client.post(
        "/api/v1/courses",
        json={"title": "Async Python", "subject_id": subject.id, "overview": "Coroutines & tasks."},
        headers=headers,
    )
    course_id = r.json()["id"]

    # The publish-guard needs at least one lesson; `seed_lesson`
    # provides it so this test exercises the green publish path
    # instead of the no-lessons rejection.
    await seed_lesson(course_id, headers)

    # S2 / ADR-0026: publish (POST /publish) keeps the course PRIVATE. A course
    # only appears in the public catalog once it is publicly LISTED — public +
    # approved + published. ``publish_and_list_course`` does the lifecycle
    # publish then sets visibility/moderation so the catalog assertion holds.
    pub = await publish_and_list_course(course_id, headers)
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
    client: AsyncClient, auth_headers, db_session: AsyncSession, publish_and_list_course
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
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules", json={"title": "M"}, headers=teacher
        )
    ).json()
    lesson = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={"title": "L", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
            headers=teacher,
        )
    ).json()

    # S2 / ADR-0026: a student can only enroll in a publicly-listed course
    # (``can_enroll`` -> ``is_publicly_listed`` OR owner). Publish + list it.
    pub = await publish_and_list_course(course_id, teacher)
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
    client: AsyncClient,
    auth_headers,
    seed_lesson,
    db_session: AsyncSession,
    publish_and_list_course,
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
    # The publish-guard requires at least one lesson; publish + list so the
    # student can reach the (enrollment-gated) review endpoint at all.
    await seed_lesson(course_id, teacher)
    await publish_and_list_course(course_id, teacher)

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


# ---------- S1.5 service-layer ungate + ownership/analytics re-checks ----------


async def test_create_course_no_instructor_gate(make_user, db_session: AsyncSession) -> None:
    # S1.5: the service no longer raises `courses.forbidden`; any active user
    # creates a Course (the instructor business-gate at services/courses.py:69
    # is removed).
    from app.schemas.course import CourseCreate
    from app.services import courses as courses_service

    subject = await _make_subject(db_session)
    user = await make_user(role=Role.user)
    course = await courses_service.create_course(
        db_session,
        owner=user,
        payload=CourseCreate(title="Ungated", subject_id=subject.id, overview="x"),
    )
    assert course.id
    assert course.owner_id == user.id


async def test_user_cannot_edit_other_users_course(make_user, db_session: AsyncSession) -> None:
    # S1.5: ungating the *route* must not let user B edit user A's course —
    # ownership stays enforced in the service (`_can_edit_course`).
    from app.core.errors import ForbiddenError
    from app.schemas.course import CourseCreate, CourseUpdate
    from app.services import courses as courses_service

    subject = await _make_subject(db_session)
    user_a = await make_user(role=Role.user)
    user_b = await make_user(role=Role.user)
    course = await courses_service.create_course(
        db_session,
        owner=user_a,
        payload=CourseCreate(title="A's course", subject_id=subject.id, overview="x"),
    )
    with pytest.raises(ForbiddenError):
        await courses_service.update_course(
            db_session,
            course_id=course.id,
            owner=user_b,
            payload=CourseUpdate(title="Hijacked"),
        )


async def test_course_analytics_owner_only(make_user, db_session: AsyncSession) -> None:
    # S1.5: analytics re-checks `cap.can_view_course_analytics` (owner-or-admin).
    from app.core.errors import ForbiddenError
    from app.schemas.course import CourseCreate
    from app.services import analytics as analytics_service
    from app.services import courses as courses_service

    subject = await _make_subject(db_session)
    owner = await make_user(role=Role.user)
    other = await make_user(role=Role.user)
    admin = await make_user(role=Role.admin)
    course = await courses_service.create_course(
        db_session,
        owner=owner,
        payload=CourseCreate(title="Stats", subject_id=subject.id, overview="x"),
    )

    # Owner can view.
    data = await analytics_service.for_course(db_session, course_id=course.id, viewer=owner)
    assert data.course_id == course.id
    # Admin can view any.
    data_admin = await analytics_service.for_course(db_session, course_id=course.id, viewer=admin)
    assert data_admin.course_id == course.id
    # A non-owner non-admin cannot.
    with pytest.raises(ForbiddenError):
        await analytics_service.for_course(db_session, course_id=course.id, viewer=other)
