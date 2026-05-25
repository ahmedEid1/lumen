"""FSRS-6 review queue (service + endpoints).

Covers:
* :func:`fsrs.ensure_card` is idempotent and creates with sane defaults
* :func:`fsrs.record_review` advances state + schedules the next due_at
* :func:`fsrs.due_cards` honours the ``due_at <= now`` filter
* ``GET /me/reviews/queue``  returns due cards with lesson + course context
* ``POST /me/reviews/{id}/grade`` updates the card and rejects bad ratings
* ``GET /me/reviews/stats``  totals the four buckets correctly
* The quiz-submit endpoint side-effects an ``ensure_card`` call
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Subject
from app.models.review_card import ReviewCard, ReviewCardState
from app.models.user import Role
from app.services import fsrs as fsrs_service

# ---------- helpers ----------


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _quiz_course(client: AsyncClient, teacher: dict, subject_id: str) -> tuple[str, str]:
    """Spin up a published course with one quiz lesson; return (course_id, quiz_lesson_id)."""
    create = await client.post(
        "/api/v1/courses",
        json={"title": "FSRS Coverage", "subject_id": subject_id, "overview": "x"},
        headers=teacher,
    )
    course_id = create.json()["id"]
    m = (
        await client.post(
            f"/api/v1/courses/{course_id}/modules",
            json={"title": "M"},
            headers=teacher,
        )
    ).json()
    quiz = (
        await client.post(
            f"/api/v1/courses/modules/{m['id']}/lessons",
            json={
                "title": "Quiz",
                "type": "quiz",
                "data": {
                    "type": "quiz",
                    "pass_score": 60,
                    "questions": [
                        {
                            "id": "q1",
                            "prompt": "Pick A",
                            "kind": "single",
                            "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                            "answer_keys": ["a"],
                        }
                    ],
                },
            },
            headers=teacher,
        )
    ).json()
    # Add a filler text lesson so the publish-time minimum-content
    # check (rebuild iter 43) is satisfied.
    await client.post(
        f"/api/v1/courses/modules/{m['id']}/lessons",
        json={"title": "Hello", "type": "text", "data": {"type": "text", "body_markdown": "x"}},
        headers=teacher,
    )
    await client.patch(
        f"/api/v1/courses/{course_id}",
        json={"status": "published"},
        headers=teacher,
    )
    return course_id, quiz["id"]


# ---------- service unit tests ----------


async def test_ensure_card_creates_with_sane_defaults(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    # Build a minimal subject/course/module/lesson tree directly so we
    # don't depend on the HTTP layer for a pure service test.
    from app.models.course import Course, CourseStatus, Lesson, LessonType, Module

    subject = await _make_subject(db_session)
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db_session.add(module)
    await db_session.flush()
    lesson = Lesson(module_id=module.id, title="L", order=0, type=LessonType.quiz, data={})
    db_session.add(lesson)
    await db_session.commit()

    card = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lesson.id)
    await db_session.commit()

    assert card.user_id == user.id
    assert card.lesson_id == lesson.id
    assert card.state == ReviewCardState.new
    assert card.total_reviews == 0
    # A fresh card should be due immediately — the dashboard surfaces it
    # right away rather than waiting on FSRS' default first interval.
    assert card.due_at <= datetime.now(UTC) + timedelta(seconds=2)
    assert card.last_reviewed_at is None


async def test_ensure_card_is_idempotent(db_session: AsyncSession, make_user) -> None:
    """Calling ensure_card twice for the same (user, lesson) yields the same row."""
    user = await make_user()
    from app.models.course import Course, CourseStatus, Lesson, LessonType, Module

    subject = await _make_subject(db_session)
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db_session.add(module)
    await db_session.flush()
    lesson = Lesson(module_id=module.id, title="L", order=0, type=LessonType.quiz, data={})
    db_session.add(lesson)
    await db_session.commit()

    first = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lesson.id)
    second = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lesson.id)
    await db_session.commit()

    assert first.id == second.id

    # Single row per (user, lesson).
    count = (
        (
            await db_session.execute(
                select(ReviewCard).where(
                    ReviewCard.user_id == user.id, ReviewCard.lesson_id == lesson.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(count) == 1


async def test_record_review_advances_state_and_due(db_session: AsyncSession, make_user) -> None:
    """Grading a 'good' rating should bump total_reviews and push due_at into the future."""
    user = await make_user()
    from app.models.course import Course, CourseStatus, Lesson, LessonType, Module

    subject = await _make_subject(db_session)
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db_session.add(module)
    await db_session.flush()
    lesson = Lesson(module_id=module.id, title="L", order=0, type=LessonType.quiz, data={})
    db_session.add(lesson)
    await db_session.commit()

    card = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lesson.id)
    await db_session.commit()
    original_due = card.due_at

    updated = await fsrs_service.record_review(db_session, card=card, rating="good")
    await db_session.commit()

    assert updated.total_reviews == 1
    assert updated.last_reviewed_at is not None
    # FSRS-6 should bump due_at forward on a successful review.
    assert updated.due_at > original_due
    # ``new`` collapses to ``learning`` once FSRS has produced a real
    # stability/difficulty for the card.
    assert updated.state in {
        ReviewCardState.learning,
        ReviewCardState.review,
    }
    assert updated.stability > 0.0


async def test_record_review_rejects_invalid_rating(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    from app.models.course import Course, CourseStatus, Lesson, LessonType, Module

    subject = await _make_subject(db_session)
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db_session.add(module)
    await db_session.flush()
    lesson = Lesson(module_id=module.id, title="L", order=0, type=LessonType.quiz, data={})
    db_session.add(lesson)
    await db_session.commit()

    card = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lesson.id)
    with pytest.raises(ValueError):
        await fsrs_service.record_review(db_session, card=card, rating="terrible")


async def test_due_cards_filters_by_due_at(db_session: AsyncSession, make_user) -> None:
    """due_cards must omit cards whose due_at is in the future."""
    user = await make_user()
    from app.models.course import Course, CourseStatus, Lesson, LessonType, Module

    subject = await _make_subject(db_session)
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db_session.add(module)
    await db_session.flush()
    l_due = Lesson(module_id=module.id, title="Due", order=0, type=LessonType.quiz, data={})
    l_future = Lesson(module_id=module.id, title="Future", order=1, type=LessonType.quiz, data={})
    db_session.add_all([l_due, l_future])
    await db_session.commit()

    due_card = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=l_due.id)
    future_card = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=l_future.id)
    future_card.due_at = datetime.now(UTC) + timedelta(days=14)
    await db_session.commit()

    queue = await fsrs_service.due_cards(db_session, user_id=user.id)
    ids = {c.id for c in queue}
    assert due_card.id in ids
    assert future_card.id not in ids


async def test_stats_buckets(db_session: AsyncSession, make_user) -> None:
    user = await make_user()
    from app.models.course import Course, CourseStatus, Lesson, LessonType, Module

    subject = await _make_subject(db_session)
    course = Course(
        owner_id=user.id,
        subject_id=subject.id,
        title="C",
        slug=f"c-{uuid.uuid4().hex[:6]}",
        overview="",
        status=CourseStatus.published,
    )
    db_session.add(course)
    await db_session.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db_session.add(module)
    await db_session.flush()
    lessons = [
        Lesson(module_id=module.id, title=f"L{i}", order=i, type=LessonType.quiz, data={})
        for i in range(3)
    ]
    db_session.add_all(lessons)
    await db_session.commit()

    # One due-now card, one in the next 7 days, one beyond.
    c0 = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lessons[0].id)
    c1 = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lessons[1].id)
    c2 = await fsrs_service.ensure_card(db_session, user_id=user.id, lesson_id=lessons[2].id)
    c1.due_at = datetime.now(UTC) + timedelta(days=2)
    c2.due_at = datetime.now(UTC) + timedelta(days=30)
    await db_session.commit()
    assert c0.due_at <= datetime.now(UTC) + timedelta(seconds=2)

    stats = await fsrs_service.stats(db_session, user_id=user.id)
    assert stats["due"] == 1
    assert stats["next_7_days"] == 1


# ---------- endpoint tests ----------


async def test_quiz_submit_creates_review_card(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """Submitting a quiz (pass or fail) enrolls the learner in the FSRS queue."""
    teacher = await auth_headers(role=Role.instructor)
    student_headers = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_headers)

    r = await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student_headers,
    )
    assert r.status_code == 200, r.text

    queue = await client.get("/api/v1/me/reviews/queue", headers=student_headers)
    assert queue.status_code == 200
    items = queue.json()["items"]
    assert len(items) == 1
    assert items[0]["lesson"]["id"] == quiz_id
    assert items[0]["lesson"]["course_id"] == course_id


async def test_grade_endpoint_updates_card(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_headers = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_headers)
    await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student_headers,
    )

    queue = (await client.get("/api/v1/me/reviews/queue", headers=student_headers)).json()
    card_id = queue["items"][0]["id"]

    graded = await client.post(
        f"/api/v1/me/reviews/{card_id}/grade",
        json={"rating": "good"},
        headers=student_headers,
    )
    assert graded.status_code == 200, graded.text
    body = graded.json()
    assert body["id"] == card_id
    assert body["total_reviews"] == 1
    assert body["last_reviewed_at"] is not None


async def test_grade_rejects_bad_rating(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_headers = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_headers)
    await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student_headers,
    )
    queue = (await client.get("/api/v1/me/reviews/queue", headers=student_headers)).json()
    card_id = queue["items"][0]["id"]

    bad = await client.post(
        f"/api/v1/me/reviews/{card_id}/grade",
        json={"rating": "okayish"},
        headers=student_headers,
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "review_card.invalid_rating"


async def test_grade_other_users_card_404(
    client: AsyncClient, auth_headers, db_session: AsyncSession
) -> None:
    """A learner cannot grade another learner's card."""
    teacher = await auth_headers(role=Role.instructor)
    alice = await auth_headers(role=Role.student)
    bob = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=alice)
    await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=alice,
    )
    queue = (await client.get("/api/v1/me/reviews/queue", headers=alice)).json()
    card_id = queue["items"][0]["id"]

    forbidden = await client.post(
        f"/api/v1/me/reviews/{card_id}/grade",
        json={"rating": "good"},
        headers=bob,
    )
    assert forbidden.status_code == 404


async def test_stats_endpoint(client: AsyncClient, auth_headers, db_session: AsyncSession) -> None:
    teacher = await auth_headers(role=Role.instructor)
    student_headers = await auth_headers(role=Role.student)
    subject = await _make_subject(db_session)
    course_id, quiz_id = await _quiz_course(client, teacher, subject.id)
    await client.post(f"/api/v1/me/enrollments/{course_id}", headers=student_headers)
    await client.post(
        f"/api/v1/me/progress/lessons/{quiz_id}/quiz",
        json={"answers": {"q1": ["a"]}},
        headers=student_headers,
    )

    stats = await client.get("/api/v1/me/reviews/stats", headers=student_headers)
    assert stats.status_code == 200
    body = stats.json()
    # one freshly-created card, due now.
    assert body["due"] >= 1
    assert "learning" in body
    assert "review" in body
    assert "next_7_days" in body
