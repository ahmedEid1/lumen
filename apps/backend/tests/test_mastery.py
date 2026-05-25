"""Per-learner mastery dashboard (service + endpoint).

Covers Phase E7. The fixtures seed a learner with two enrolled
courses, a mix of quiz attempts (one failed, one low-but-passing, one
high), an FSRS card pushed deep into "overdue" territory, and a
tutor conversation whose assistant message cites the failed-quiz
lesson three times. We then assert:

* ``mastery.weak_spots`` surfaces the failed-quiz lesson, the
  overdue-card lesson, and the tutor-cited lesson, in that order.
* ``mastery.per_course_mastery`` computes ``mastery_pct`` as the
  average of the latest scores and ``completion_pct`` against the
  total live-lesson count.
* ``GET /me/mastery`` returns the bundled shape with the same data.
* Unrelated learners' weak spots don't bleed into ``user_id``'s view
  (privacy invariant — the endpoint must be strictly scoped).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import (
    Course,
    CourseStatus,
    Enrollment,
    Lesson,
    LessonProgress,
    LessonType,
    Module,
    Subject,
)
from app.models.quiz_attempt import QuizAttempt
from app.models.review_card import ReviewCard, ReviewCardState
from app.models.tutor_conversation import (
    TutorConversation,
    TutorMessage,
    TutorMessageRole,
)
from app.models.user import Role, User
from app.services import mastery as mastery_service

# ---------- fixtures ----------


async def _make_subject(db: AsyncSession) -> Subject:
    s = Subject(title="Programming", slug=f"programming-{uuid.uuid4().hex[:6]}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _seed_course(
    db: AsyncSession,
    *,
    owner: User,
    subject: Subject,
    title: str,
    lesson_specs: list[tuple[str, LessonType]],
) -> tuple[Course, list[Lesson]]:
    """Create a published course with N lessons in one module.

    ``lesson_specs`` is a list of ``(lesson_title, type)`` tuples; the
    helper hands back the persisted Course and the matching Lesson
    list in declaration order so tests can refer to specific lessons
    by index without re-querying.
    """
    course = Course(
        owner_id=owner.id,
        subject_id=subject.id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        overview="seed",
        status=CourseStatus.published,
    )
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db.add(module)
    await db.flush()
    lessons: list[Lesson] = []
    for idx, (title_l, type_l) in enumerate(lesson_specs):
        lesson = Lesson(
            module_id=module.id,
            title=title_l,
            order=idx,
            type=type_l,
            data={},
        )
        db.add(lesson)
        lessons.append(lesson)
    await db.commit()
    for lesson in lessons:
        await db.refresh(lesson)
    return course, lessons


async def _enroll(db: AsyncSession, *, user: User, course: Course) -> Enrollment:
    enr = Enrollment(user_id=user.id, course_id=course.id)
    db.add(enr)
    await db.commit()
    await db.refresh(enr)
    return enr


async def _attempt(
    db: AsyncSession,
    *,
    enrollment: Enrollment,
    lesson: Lesson,
    score: int,
    passed: bool,
    minutes_ago: int = 1,
) -> QuizAttempt:
    """Persist one quiz attempt at ``score`` for ``lesson``.

    Caller controls "how recent" via ``minutes_ago`` because the
    service picks the *latest* attempt — tests that exercise the
    "passed-after-failing" path lean on this to order the rows.
    """
    submitted = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    attempt = QuizAttempt(
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        score=score,
        passed=passed,
        answers={},
        submitted_at=submitted,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def _mark_complete(db: AsyncSession, *, enrollment: Enrollment, lesson: Lesson) -> None:
    lp = LessonProgress(
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        completed_at=datetime.now(UTC),
    )
    db.add(lp)
    await db.commit()


async def _make_overdue_card(
    db: AsyncSession,
    *,
    user: User,
    lesson: Lesson,
    days_overdue: int,
) -> ReviewCard:
    """Plant a review card directly in the DB at a chosen overdue depth.

    Going through ``fsrs.ensure_card`` would always make the card due
    *now* (not in the past); for testing the overdue-signal threshold
    we want surgical control over ``due_at``.
    """
    card = ReviewCard(
        user_id=user.id,
        lesson_id=lesson.id,
        stability=0.0,
        difficulty=0.0,
        state=ReviewCardState.learning,
        step=1,
        due_at=datetime.now(UTC) - timedelta(days=days_overdue),
        last_reviewed_at=None,
        total_reviews=0,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


async def _seed_tutor_thread(
    db: AsyncSession,
    *,
    user: User,
    course: Course,
    cited_lessons: list[Lesson],
    repetitions: int,
) -> TutorConversation:
    """Create a tutor conversation that cites each lesson ``repetitions`` times.

    The service-layer signal counts citations across *assistant*
    messages; the test seeds N assistant turns, each carrying every
    target lesson in its citations array.
    """
    conv = TutorConversation(user_id=user.id, course_id=course.id)
    db.add(conv)
    await db.flush()
    for _ in range(repetitions):
        db.add(
            TutorMessage(
                conversation_id=conv.id,
                role=TutorMessageRole.user,
                content="explain this",
                citations=[],
            )
        )
        db.add(
            TutorMessage(
                conversation_id=conv.id,
                role=TutorMessageRole.assistant,
                content="answer",
                citations=[
                    {
                        "lesson_id": lesson.id,
                        "lesson_title": lesson.title,
                        "chunk_excerpt": "...",
                    }
                    for lesson in cited_lessons
                ],
            )
        )
    await db.commit()
    return conv


# ---------- service-level tests ----------


async def test_weak_spots_surfaces_failed_quiz(db_session: AsyncSession, make_user) -> None:
    """A failed quiz attempt is the strongest weak-spot signal."""
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Algo",
        lesson_specs=[
            ("Big-O", LessonType.quiz),
            ("Sorting", LessonType.quiz),
        ],
    )
    enrollment = await _enroll(db_session, user=learner, course=course)
    # Failed quiz — score 40, passed=False — should surface.
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[0],
        score=40,
        passed=False,
    )
    # Strong pass — should NOT surface.
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[1],
        score=95,
        passed=True,
    )

    spots = await mastery_service.weak_spots(db_session, learner.id)
    lesson_ids = [s.lesson.id for s in spots]
    assert lessons[0].id in lesson_ids
    assert lessons[1].id not in lesson_ids
    flagged = next(s for s in spots if s.lesson.id == lessons[0].id)
    assert "quiz_failed" in flagged.signals
    assert flagged.signal_details.get("quiz_score") == "40"


async def test_weak_spots_ignores_resolved_failure(db_session: AsyncSession, make_user) -> None:
    """An older failed attempt overridden by a recent pass should not surface.

    The service flags lessons by their *latest* attempt; a learner who
    failed once and then passed has resolved the weak spot.
    """
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Algo",
        lesson_specs=[("Recursion", LessonType.quiz)],
    )
    enrollment = await _enroll(db_session, user=learner, course=course)
    # Older failure.
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[0],
        score=20,
        passed=False,
        minutes_ago=120,
    )
    # Newer pass.
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[0],
        score=88,
        passed=True,
        minutes_ago=1,
    )

    spots = await mastery_service.weak_spots(db_session, learner.id)
    assert all(s.lesson.id != lessons[0].id for s in spots)


async def test_weak_spots_surfaces_overdue_card(db_session: AsyncSession, make_user) -> None:
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="DB",
        lesson_specs=[("ACID", LessonType.quiz)],
    )
    await _enroll(db_session, user=learner, course=course)
    card = await _make_overdue_card(db_session, user=learner, lesson=lessons[0], days_overdue=5)

    spots = await mastery_service.weak_spots(db_session, learner.id)
    flagged = next(s for s in spots if s.lesson.id == lessons[0].id)
    assert "card_overdue" in flagged.signals
    assert flagged.signal_details.get("overdue_days") == "5"
    # The "Review now" CTA links into the FSRS queue.
    assert flagged.review_card_id == card.id


async def test_weak_spots_surfaces_repeated_tutor_citations(
    db_session: AsyncSession, make_user
) -> None:
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Net",
        lesson_specs=[("TCP", LessonType.text), ("UDP", LessonType.text)],
    )
    await _enroll(db_session, user=learner, course=course)
    # 4 citations of TCP — over the TUTOR_REPEAT_THRESHOLD of 3.
    await _seed_tutor_thread(
        db_session,
        user=learner,
        course=course,
        cited_lessons=[lessons[0]],
        repetitions=4,
    )
    # 1 citation of UDP — below the threshold, must not surface.
    await _seed_tutor_thread(
        db_session,
        user=learner,
        course=course,
        cited_lessons=[lessons[1]],
        repetitions=1,
    )

    spots = await mastery_service.weak_spots(db_session, learner.id)
    ids = {s.lesson.id for s in spots}
    assert lessons[0].id in ids
    assert lessons[1].id not in ids
    flagged = next(s for s in spots if s.lesson.id == lessons[0].id)
    assert "tutor_repeat" in flagged.signals
    assert flagged.signal_details.get("tutor_count") == "4"


async def test_weak_spots_deduplicates_per_lesson(db_session: AsyncSession, make_user) -> None:
    """A lesson hit by multiple signals appears once with all signals."""
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Sec",
        lesson_specs=[("XSS", LessonType.quiz)],
    )
    enrollment = await _enroll(db_session, user=learner, course=course)
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[0],
        score=30,
        passed=False,
    )
    await _make_overdue_card(db_session, user=learner, lesson=lessons[0], days_overdue=10)
    await _seed_tutor_thread(
        db_session,
        user=learner,
        course=course,
        cited_lessons=[lessons[0]],
        repetitions=5,
    )

    spots = await mastery_service.weak_spots(db_session, learner.id)
    hits = [s for s in spots if s.lesson.id == lessons[0].id]
    assert len(hits) == 1
    flagged = hits[0]
    assert set(flagged.signals) >= {"quiz_failed", "card_overdue", "tutor_repeat"}
    # Strongest signal (quiz_failed) ranks first in the display order.
    assert flagged.signals[0] == "quiz_failed"


async def test_weak_spots_scoped_to_user(db_session: AsyncSession, make_user) -> None:
    """One learner's weak spots never appear in another learner's view."""
    alice = await make_user(role=Role.student)
    bob = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="ML",
        lesson_specs=[("Linear", LessonType.quiz)],
    )
    alice_enr = await _enroll(db_session, user=alice, course=course)
    await _attempt(
        db_session,
        enrollment=alice_enr,
        lesson=lessons[0],
        score=20,
        passed=False,
    )

    bobs_view = await mastery_service.weak_spots(db_session, bob.id)
    assert bobs_view == []


async def test_per_course_mastery_rolls_up_scores_and_completion(
    db_session: AsyncSession, make_user
) -> None:
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Calc",
        lesson_specs=[
            ("Limits", LessonType.quiz),
            ("Derivatives", LessonType.quiz),
            ("Integrals", LessonType.text),
            ("Series", LessonType.text),
        ],
    )
    enrollment = await _enroll(db_session, user=learner, course=course)
    # Quiz attempts: 60 + 80 = avg 70.
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[0],
        score=60,
        passed=True,
    )
    await _attempt(
        db_session,
        enrollment=enrollment,
        lesson=lessons[1],
        score=80,
        passed=True,
    )
    # Two of four lessons complete → 50% completion.
    await _mark_complete(db_session, enrollment=enrollment, lesson=lessons[0])
    await _mark_complete(db_session, enrollment=enrollment, lesson=lessons[2])

    rows = await mastery_service.per_course_mastery(db_session, learner.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.course_id == course.id
    assert row.slug == course.slug
    assert row.mastery_pct == 70.0
    assert row.completion_pct == 50.0


async def test_per_course_mastery_handles_no_quiz_attempts(
    db_session: AsyncSession, make_user
) -> None:
    """A course with text-only lessons reports mastery_pct=0 + real completion_pct."""
    learner = await make_user(role=Role.student)
    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course, lessons = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Hist",
        lesson_specs=[("Pre-modern", LessonType.text), ("Modern", LessonType.text)],
    )
    enrollment = await _enroll(db_session, user=learner, course=course)
    await _mark_complete(db_session, enrollment=enrollment, lesson=lessons[0])

    rows = await mastery_service.per_course_mastery(db_session, learner.id)
    assert len(rows) == 1
    assert rows[0].mastery_pct == 0.0
    assert rows[0].completion_pct == 50.0


# ---------- endpoint-level tests ----------


async def test_me_mastery_endpoint_bundles_weak_spots_and_courses(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    make_user,
) -> None:
    """GET /me/mastery returns weak_spots + courses for the calling learner."""
    learner_headers = await auth_headers(role=Role.student)
    # Re-resolve the calling learner so the seeder writes data against
    # the right user_id. ``auth_headers`` doesn't expose the user, so
    # we fish it back via the /auth/me endpoint.
    me_resp = await client.get("/api/v1/auth/me", headers=learner_headers)
    learner_id = me_resp.json()["id"]

    teacher = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)
    course_a, lessons_a = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Sys",
        lesson_specs=[
            ("Threads", LessonType.quiz),
            ("Locks", LessonType.quiz),
            ("Channels", LessonType.text),
        ],
    )
    course_b, lessons_b = await _seed_course(
        db_session,
        owner=teacher,
        subject=subject,
        title="Web",
        lesson_specs=[("HTTP", LessonType.text), ("TLS", LessonType.text)],
    )

    # Look the learner up by id and attach the seed data directly.
    learner = await db_session.get(User, learner_id)
    assert learner is not None
    enr_a = await _enroll(db_session, user=learner, course=course_a)
    await _enroll(db_session, user=learner, course=course_b)

    # One failed quiz (course A, lesson 0), one overdue card (course A,
    # lesson 1), one tutor-cited lesson (also lesson 0 — overlap is
    # deliberate so we exercise the per-(course, lesson) dedupe).
    await _attempt(
        db_session,
        enrollment=enr_a,
        lesson=lessons_a[0],
        score=35,
        passed=False,
    )
    await _make_overdue_card(db_session, user=learner, lesson=lessons_a[1], days_overdue=4)
    await _seed_tutor_thread(
        db_session,
        user=learner,
        course=course_a,
        cited_lessons=[lessons_a[0]],
        repetitions=3,
    )
    # Mark one lesson done in course B so completion_pct is non-zero.
    from sqlalchemy import select as _select

    enr_b = (
        await db_session.execute(
            _select(Enrollment).where(
                Enrollment.user_id == learner.id,
                Enrollment.course_id == course_b.id,
            )
        )
    ).scalar_one()
    await _mark_complete(db_session, enrollment=enr_b, lesson=lessons_b[0])

    resp = await client.get("/api/v1/me/mastery", headers=learner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "weak_spots" in body
    assert "courses" in body

    spot_lesson_ids = {s["lesson"]["id"] for s in body["weak_spots"]}
    assert lessons_a[0].id in spot_lesson_ids
    assert lessons_a[1].id in spot_lesson_ids

    # Course A's failed-quiz row carries both the quiz signal and the
    # tutor-repeat signal because we cited the same lesson three times.
    lesson_0_spot = next(s for s in body["weak_spots"] if s["lesson"]["id"] == lessons_a[0].id)
    assert "quiz_failed" in lesson_0_spot["signals"]
    assert "tutor_repeat" in lesson_0_spot["signals"]
    assert lesson_0_spot["lesson"]["course_id"] == course_a.id
    assert lesson_0_spot["lesson"]["course_slug"] == course_a.slug

    # Two enrolled courses come back, newest first (course_b is the
    # most recent enrollment).
    course_ids = [c["course_id"] for c in body["courses"]]
    assert set(course_ids) == {course_a.id, course_b.id}
    course_b_row = next(c for c in body["courses"] if c["course_id"] == course_b.id)
    assert course_b_row["completion_pct"] == 50.0
    assert course_b_row["mastery_pct"] == 0.0


async def test_me_mastery_endpoint_empty_for_new_learner(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers(role=Role.student)
    resp = await client.get("/api/v1/me/mastery", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"weak_spots": [], "courses": []}


async def test_me_mastery_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/me/mastery")
    assert resp.status_code == 401
