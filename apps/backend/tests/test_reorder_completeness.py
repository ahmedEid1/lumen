"""Regression: reorder must cover every row exactly once.

Before iteration 41 ``reorder_modules`` / ``reorder_lessons`` set every
row's order to a negative temp value (-1, -2, ...) to dodge the
``(course_id, order)`` / ``(module_id, order)`` unique constraint, then
assigned new orders only to the rows the caller named. A partial
mapping — easy to craft from a buggy mobile client, a replay, or a
malicious authenticated user — left the unmentioned rows stuck at the
negative temp value forever. Negative orders sort first, so the
syllabus silently rearranged itself, hoisting random modules/lessons
to the top.

Two additional invariants we now enforce:

* target orders must be non-negative (else the next reorder collides
  on the same negative temp space);
* target orders must be unique within the request (else the assignment
  pass crashes the unique constraint with a 5xx).

For lessons specifically, soft-deleted rows had the same
post-condition bug because they shared the unique constraint with
live rows. We now nudge them past the live range so a future reorder
can't collide with them either.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Lesson, LessonType, Module, Subject
from app.models.user import Role
from app.services import courses as courses_service


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _course_with_modules(
    client: AsyncClient, headers, subject_id: str, n_modules: int = 3
) -> tuple[str, list[str]]:
    c = await client.post(
        "/api/v1/courses",
        json={"title": "C", "subject_id": subject_id, "overview": "x"},
        headers=headers,
    )
    course_id = c.json()["id"]
    module_ids: list[str] = []
    for i in range(n_modules):
        m = await client.post(
            f"/api/v1/courses/{course_id}/modules",
            json={"title": f"M{i}", "description": ""},
            headers=headers,
        )
        module_ids.append(m.json()["id"])
    return course_id, module_ids


# ---------- modules ----------


async def test_partial_module_mapping_is_rejected(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, ids = await _course_with_modules(client, teacher, subject.id, 3)

    # Mapping covers only the first of three modules.
    r = await client.post(
        f"/api/v1/courses/{course_id}/modules/order",
        json={"order": {ids[0]: 0}},
        headers=teacher,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "modules.partial_order"

    # Sanity: the syllabus did NOT silently rearrange (orders all >= 0).
    detail = await client.get(f"/api/v1/courses/{course_id}", headers=teacher)
    orders = [m["order"] for m in detail.json()["modules"]]
    assert all(o >= 0 for o in orders), orders


async def test_duplicate_module_target_orders_rejected(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, ids = await _course_with_modules(client, teacher, subject.id, 3)

    r = await client.post(
        f"/api/v1/courses/{course_id}/modules/order",
        json={"order": {ids[0]: 0, ids[1]: 0, ids[2]: 1}},
        headers=teacher,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "modules.duplicate_order"


async def test_negative_module_target_orders_rejected(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, ids = await _course_with_modules(client, teacher, subject.id, 3)

    r = await client.post(
        f"/api/v1/courses/{course_id}/modules/order",
        json={"order": {ids[0]: 0, ids[1]: -1, ids[2]: 1}},
        headers=teacher,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "modules.negative_order"


async def test_full_module_mapping_still_works(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_id, ids = await _course_with_modules(client, teacher, subject.id, 3)

    r = await client.post(
        f"/api/v1/courses/{course_id}/modules/order",
        json={"order": {ids[2]: 0, ids[0]: 1, ids[1]: 2}},
        headers=teacher,
    )
    assert r.status_code == 200, r.text
    detail = await client.get(f"/api/v1/courses/{course_id}", headers=teacher)
    by_order = {m["order"]: m["id"] for m in detail.json()["modules"]}
    assert by_order[0] == ids[2]
    assert by_order[1] == ids[0]
    assert by_order[2] == ids[1]


# ---------- lessons (with soft-delete) ----------


async def test_lesson_reorder_skips_soft_deleted_and_avoids_collision(
    db_session: AsyncSession, make_user
) -> None:
    """Soft-deleted lessons must not collide with the new ordering."""
    teacher = await make_user(role=Role.instructor)
    subject = Subject(title="P", slug=f"p-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.flush()
    from app.models.course import Course, CourseStatus

    course = Course(
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="x",
        owner_id=teacher.id,
        subject_id=subject.id,
        status=CourseStatus.draft,
    )
    db_session.add(course)
    await db_session.flush()
    mod = Module(course_id=course.id, title="M", order=0)
    db_session.add(mod)
    await db_session.flush()
    lessons = []
    for i in range(3):
        l = Lesson(
            module_id=mod.id,
            title=f"L{i}",
            order=i,
            type=LessonType.text,
            data={"type": "text", "body_markdown": "x"},
        )
        db_session.add(l)
        lessons.append(l)
    await db_session.commit()

    # Soft-delete the middle one (was at order=1).
    lessons[1].deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Reorder the two live lessons; the deleted one (still at order=1)
    # would collide with the new order=1 target without the parking step.
    await courses_service.reorder_lessons(
        db_session,
        module_id=mod.id,
        owner=teacher,
        mapping={lessons[2].id: 0, lessons[0].id: 1},
    )
    await db_session.commit()

    await db_session.refresh(lessons[0])
    await db_session.refresh(lessons[1])
    await db_session.refresh(lessons[2])
    assert lessons[2].order == 0
    assert lessons[0].order == 1
    # Soft-deleted lesson parked past the live range (no negative leftover).
    assert lessons[1].order >= 2


async def test_lesson_reorder_partial_mapping_rejected(
    db_session: AsyncSession, make_user
) -> None:
    teacher = await make_user(role=Role.instructor)
    subject = Subject(title="P", slug=f"p-{uuid.uuid4().hex[:6]}")
    db_session.add(subject)
    await db_session.flush()
    from app.models.course import Course, CourseStatus

    course = Course(
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="x",
        owner_id=teacher.id,
        subject_id=subject.id,
        status=CourseStatus.draft,
    )
    db_session.add(course)
    await db_session.flush()
    mod = Module(course_id=course.id, title="M", order=0)
    db_session.add(mod)
    await db_session.flush()
    lessons = []
    for i in range(3):
        l = Lesson(
            module_id=mod.id,
            title=f"L{i}",
            order=i,
            type=LessonType.text,
            data={"type": "text", "body_markdown": "x"},
        )
        db_session.add(l)
        lessons.append(l)
    await db_session.commit()

    from app.core.errors import ValidationAppError
    import pytest

    with pytest.raises(ValidationAppError) as exc:
        await courses_service.reorder_lessons(
            db_session,
            module_id=mod.id,
            owner=teacher,
            mapping={lessons[0].id: 0},
        )
    assert exc.value.code == "lessons.partial_order"
