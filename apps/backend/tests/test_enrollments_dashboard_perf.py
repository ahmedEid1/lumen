"""Regression: dashboard listing must not N+1 over progress.

Before rebuild Fix B1, ``list_my_enrollments`` called
``enrollment_service.progress_pct(...)`` once per enrollment, and each
call hit two queries (``count_lessons_in_course`` + the
``count_completed_lessons`` aggregate). N enrollments -> 2N round-
trips to Postgres -- a single dashboard request from a learner
enrolled in 50 courses cost 100 progress queries on top of the
courses+stats fetches.

The fix introduced ``courses_repo.progress_pcts_for_enrollments``, a
batched lookup that groups by course (for live-lesson totals) and by
enrollment (for completions), then divides in Python. The total query
budget for the progress portion of the dashboard collapses from 2N to
a flat 2.

This test seeds a learner enrolled in five courses with mixed
progress, then counts how many SELECTs land on ``lesson_progress``
and on ``lessons`` (filtered to the live-lesson count path). The
listing must return correct percentages AND issue no more than 2
progress-related queries regardless of N.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.course import Subject
from app.models.user import Role


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _enrolled_with_progress(
    client: AsyncClient,
    teacher: dict,
    student: dict,
    subject_id: str,
    title: str,
    seed_lesson,
    *,
    completed_lessons: int,
    extra_lessons: int = 0,
) -> str:
    """Create + publish a course with ``1 + extra_lessons`` lessons; mark
    ``completed_lessons`` of them complete for ``student``."""
    create = await client.post(
        "/api/v1/courses",
        json={"title": title, "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    # ``seed_lesson`` is a positional-only helper — it creates a fresh
    # module + lesson per call with the same canned title. The original
    # test passed ``title=f"L{i + 2}"`` to disambiguate the rows in test
    # output, but the helper never accepted that kwarg and the perf
    # assertion doesn't depend on lesson titles being unique. Just
    # call the helper N+1 times; each call creates a new module +
    # lesson pair which is what the batched-progress fetcher needs.
    lesson_ids = [await seed_lesson(course_id, teacher)]
    for _ in range(extra_lessons):
        lesson_ids.append(await seed_lesson(course_id, teacher))
    await client.patch(
        f"/api/v1/courses/{course_id}", json={"status": "published"}, headers=teacher
    )
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student)
    for lid in lesson_ids[:completed_lessons]:
        await client.post(
            f"/api/v1/me/progress/lessons/{lid}",
            json={"completed": True},
            headers=student,
        )
    return course_id


@pytest.mark.asyncio
async def test_dashboard_progress_is_batched(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    _engine: AsyncEngine,
    seed_lesson,
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)

    # 5 courses, each with 2 lessons; complete 0..2 of them in turn so
    # the resulting progress percentages span 0 / 50 / 100 and the
    # batched query has to handle "no progress rows" as well.
    expected_pcts: dict[str, float] = {}
    for i in range(5):
        completed = i % 3  # 0, 1, 2, 0, 1
        cid = await _enrolled_with_progress(
            client,
            teacher,
            student,
            subject.id,
            f"C{i}",
            seed_lesson,
            completed_lessons=completed,
            extra_lessons=1,  # 2 lessons total per course
        )
        expected_pcts[cid] = round(completed / 2 * 100.0, 1)

    # Count SELECTs that touch lesson_progress or lessons-with-aggregate
    # during the listing call.
    progress_queries: list[str] = []

    def _on_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        s = statement.lower()
        # Count the two aggregate paths the batched fetcher uses:
        # GROUP BY module.course_id (live-lesson totals) and
        # GROUP BY lesson_progress.enrollment_id (completions).
        if ("count(" in s) and ("from lesson_progress" in s or "from modules" in s):
            progress_queries.append(statement)

    sync_engine = _engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _on_execute)
    try:
        r = await client.get("/api/v1/me/enrollments", headers=student)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_execute)

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 5
    actual_pcts = {e["course"]["id"]: e["progress_pct"] for e in body}
    assert actual_pcts == expected_pcts

    # Pre-fix this would be 2 per enrollment = 10 (or 5 with the lesson
    # total cached, but the original code didn't cache). The batched
    # fix issues 2 aggregates regardless of N.
    assert len(progress_queries) <= 2, (
        f"Expected <=2 batched progress queries, got {len(progress_queries)}:\n"
        + "\n".join(progress_queries)
    )
