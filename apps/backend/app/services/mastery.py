"""Per-learner mastery service.

Rebuild Phase E7. The mastery surface tells a learner *what to revisit
next* by combining three independent signal streams the platform has
been quietly accumulating:

1. **E4 — FSRS-6 review queue.** A card whose ``due_at`` has passed (and
   the further past, the worse) is the spaced-repetition algorithm
   telling us the learner's memory of that lesson is decaying. We
   surface the most-overdue cards as weak spots so the dashboard
   funnels the learner toward the review queue without making them
   reason about ``due_at`` timestamps.

2. **Quiz attempts.** A failing or low-scoring quiz attempt is the most
   direct "I don't understand this" signal we have. We aggregate the
   learner's attempts per lesson (taking the *latest* attempt, not the
   minimum — a learner who tried, failed, and then passed has resolved
   the weak spot) and flag the ones where the latest score is below
   the lesson's pass threshold or below 70%.

3. **E1 — tutor conversations.** When a learner asks the course tutor
   a question, the tutor's reply carries citations to specific lessons.
   A learner who has the tutor pointing at the same lesson five
   different times is, in proxy form, telling us "I keep coming back
   to this idea". We tally citations across all the learner's tutor
   messages and flag the lessons cited most often.

The three signals deliberately overlap — a learner who failed a quiz
on lesson L will also have an overdue FSRS card on L and may well have
asked the tutor about L. ``weak_spots`` deduplicates per (course,
lesson) and accumulates the signals onto a single row so the UI shows
one entry per actionable item with all the reasons stacked as pills.

The second function, ``per_course_mastery``, gives a coarser
top-of-page summary: per enrolled course, two numbers — ``mastery_pct``
(average of the latest quiz scores in the course) and ``completion_pct``
(fraction of lessons marked complete). They're computed together so the
dashboard issues *one* API call to populate both the weak-spots list
and the per-course progress bars.

Performance: the service issues a small fixed number of aggregate
SQL queries (no per-lesson loops). Worst case is O(enrollments) for
per-course mastery, plus one query each for the three weak-spot
signals. All deduplication / scoring happens in Python on already-
projected rows, not via DB-side joins, which keeps the query plans
trivially indexable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import (
    Course,
    Enrollment,
    Lesson,
    LessonProgress,
    Module,
)
from app.models.quiz_attempt import QuizAttempt
from app.models.review_card import ReviewCard
from app.models.tutor_conversation import TutorConversation, TutorMessage, TutorMessageRole

# How many weak-spot rows we surface by default. Ten is the sweet spot
# between "actionable list" (you can imagine working through it) and
# "exhaustive triage" (where everything is a priority so nothing is).
DEFAULT_WEAK_SPOT_LIMIT = 10

# Quiz score below which a lesson is flagged as a weak spot. We use a
# constant rather than reading per-quiz ``pass_score`` because (a) most
# quizzes use the same 60-pct threshold by convention and (b) a lesson
# with a 70-pct quiz threshold the learner just barely cleared is still
# arguably weak — the dashboard's job is to be cautious, not pedantic.
QUIZ_WEAK_SCORE = 70

# How overdue a review card has to be (in days) before it counts as a
# weak-spot signal on its own. Less than this and the learner is
# probably just slightly behind on the regular queue cadence — pulling
# them out into the dashboard would be alarmist.
CARD_OVERDUE_DAYS = 2

# Minimum tutor-citation count for a lesson to count as "asked about
# repeatedly". One-off citations are noise; three or more pointing at
# the same lesson is the learner circling back.
TUTOR_REPEAT_THRESHOLD = 3


@dataclass(frozen=True)
class WeakSpotLesson:
    """Slimmed lesson + course context attached to a weak spot."""

    id: str
    title: str
    course_id: str
    course_slug: str
    course_title: str


@dataclass(frozen=True)
class WeakSpot:
    """One actionable row on the mastery dashboard.

    ``signals`` is the list of reasons the lesson is flagged, formatted
    for direct display as small badge pills. The strings are plain
    English here — the API layer translates them to wire-friendly tags
    (``quiz_low``, ``card_overdue``, ``tutor_repeat``) so the frontend
    can localise. The dataclass exposes both: ``signals`` for the
    machine-readable codes, ``signal_details`` for human-readable
    quantification ("60%", "3 days", "asked 5 times").
    """

    lesson: WeakSpotLesson
    signals: list[str]
    signal_details: dict[str, str]
    # An optional review_card_id when the FSRS queue has a due card for
    # this lesson — lets the UI deep-link the "Review now" CTA to the
    # spaced-repetition surface rather than the lesson player.
    review_card_id: str | None


@dataclass(frozen=True)
class CourseMastery:
    """One enrolled-course row on the mastery dashboard."""

    course_id: str
    slug: str
    title: str
    mastery_pct: float
    completion_pct: float


# ---------- weak-spot signal collectors ----------


async def _latest_quiz_score_per_lesson(
    db: AsyncSession, user_id: str
) -> dict[str, tuple[int, bool]]:
    """Latest quiz attempt per lesson for this learner.

    Returns ``{lesson_id: (score, passed)}`` using the most recent
    submission. Earlier failures don't shadow a later pass — we only
    flag lessons where the learner's *current* state of knowledge is
    weak, not lessons they once struggled with and now master.
    """
    # Sub-select the latest attempt id per (enrollment, lesson) and
    # then join back. We use ``row_number()`` rather than ``MAX(id)``
    # because nanoid ids aren't time-sortable.
    rn = (
        func.row_number()
        .over(
            partition_by=(QuizAttempt.lesson_id,),
            order_by=QuizAttempt.submitted_at.desc(),
        )
        .label("rn")
    )
    inner = (
        select(QuizAttempt.lesson_id, QuizAttempt.score, QuizAttempt.passed, rn)
        .join(Enrollment, Enrollment.id == QuizAttempt.enrollment_id)
        .where(Enrollment.user_id == user_id)
        .subquery()
    )
    res = await db.execute(
        select(inner.c.lesson_id, inner.c.score, inner.c.passed).where(inner.c.rn == 1)
    )
    return {row.lesson_id: (int(row.score), bool(row.passed)) for row in res.all()}


async def _tutor_citation_counts(db: AsyncSession, user_id: str) -> dict[str, int]:
    """Aggregate lesson-citation counts across all of this learner's tutor messages.

    Citations live as a JSONB array on each assistant message. We pull
    every assistant message the learner has authored a conversation
    for, walk the JSON in Python, and tally ``lesson_id`` occurrences.
    Doing the aggregation in Python keeps the SQL portable (no
    Postgres-specific ``jsonb_array_elements`` joins) at the cost of
    fetching the JSON blobs — acceptable because (a) tutor message
    counts per learner stay in the hundreds at most and (b) the
    citation arrays are small (``top_k=5``).
    """
    res = await db.execute(
        select(TutorMessage.citations)
        .join(TutorConversation, TutorConversation.id == TutorMessage.conversation_id)
        .where(
            TutorConversation.user_id == user_id,
            TutorMessage.role == TutorMessageRole.assistant,
        )
    )
    counts: dict[str, int] = defaultdict(int)
    for (citations,) in res.all():
        if not citations:
            continue
        for cite in citations:
            lid = cite.get("lesson_id") if isinstance(cite, dict) else None
            if lid:
                counts[str(lid)] += 1
    return dict(counts)


async def _overdue_cards(
    db: AsyncSession, user_id: str, *, now: datetime | None = None
) -> dict[str, ReviewCard]:
    """Review cards whose ``due_at`` is more than a day in the past.

    Returns ``{lesson_id: ReviewCard}`` keyed by lesson so the
    dedupe-by-(course, lesson) walk can attach the card id to the
    matching weak spot.
    """
    cutoff = now or datetime.now(UTC)
    res = await db.execute(
        select(ReviewCard).where(
            ReviewCard.user_id == user_id,
            ReviewCard.due_at <= cutoff,
        )
    )
    return {c.lesson_id: c for c in res.scalars().all()}


async def _lessons_by_id(db: AsyncSession, lesson_ids: list[str]) -> dict[str, WeakSpotLesson]:
    """Bulk-resolve lesson context (title + course slug/title) for weak-spot rows.

    Strips soft-deleted lessons so the surface never points at content
    that no longer exists.
    """
    if not lesson_ids:
        return {}
    res = await db.execute(
        select(
            Lesson.id,
            Lesson.title,
            Course.id.label("course_id"),
            Course.slug.label("course_slug"),
            Course.title.label("course_title"),
        )
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Lesson.id.in_(lesson_ids),
            Lesson.deleted_at.is_(None),
            Course.deleted_at.is_(None),
        )
    )
    return {
        row.id: WeakSpotLesson(
            id=row.id,
            title=row.title,
            course_id=row.course_id,
            course_slug=row.course_slug,
            course_title=row.course_title,
        )
        for row in res.all()
    }


# ---------- public API ----------


async def weak_spots(
    db: AsyncSession,
    user_id: str,
    limit: int = DEFAULT_WEAK_SPOT_LIMIT,
    *,
    now: datetime | None = None,
) -> list[WeakSpot]:
    """Surface the top-N lessons this learner should revisit.

    Combines the three signal sources described in the module
    docstring, deduplicates per lesson, ranks by accumulated signal
    weight, and returns at most ``limit`` rows. The ranking weight is:

    * a failed quiz (``passed=False``) is the strongest signal
      (weight 3)
    * a low-but-passing quiz score is weight 2
    * an overdue review card is weight 2 (scaled by overdue-days,
      capped)
    * repeat tutor citations are weight 1 per multiple of
      ``TUTOR_REPEAT_THRESHOLD``

    Lessons with zero accumulated weight are not included even if a
    weak signal touched them — e.g. a single overdue card by one hour
    is below the ``CARD_OVERDUE_DAYS`` threshold and won't fire.

    The ``signals`` list on each row is ordered by weight (strongest
    first) so the UI's pill row reads "failed quiz · 3 days overdue ·
    asked 5 times" rather than the reverse.
    """
    cutoff = now or datetime.now(UTC)

    quiz_scores = await _latest_quiz_score_per_lesson(db, user_id)
    cards = await _overdue_cards(db, user_id, now=cutoff)
    tutor_counts = await _tutor_citation_counts(db, user_id)

    # Build the candidate (lesson_id → weight, signal codes, details).
    # We compute everything keyed by lesson, then bulk-resolve lesson
    # context in one query and assemble the final list.
    accum: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "weight": 0,
            "signals": [],
            "details": {},
            "review_card_id": None,
        }
    )

    for lid, (score, passed) in quiz_scores.items():
        if not passed:
            entry = accum[lid]
            entry["weight"] = int(entry["weight"]) + 3
            signals = entry["signals"]
            assert isinstance(signals, list)
            signals.append("quiz_failed")
            details = entry["details"]
            assert isinstance(details, dict)
            details["quiz_score"] = f"{score}"
        elif score < QUIZ_WEAK_SCORE:
            entry = accum[lid]
            entry["weight"] = int(entry["weight"]) + 2
            signals = entry["signals"]
            assert isinstance(signals, list)
            signals.append("quiz_low")
            details = entry["details"]
            assert isinstance(details, dict)
            details["quiz_score"] = f"{score}"

    for lid, card in cards.items():
        overdue_days = max(0, (cutoff - card.due_at).days)
        if overdue_days < CARD_OVERDUE_DAYS:
            continue
        entry = accum[lid]
        entry["weight"] = int(entry["weight"]) + min(4, 2 + overdue_days // 7)
        signals = entry["signals"]
        assert isinstance(signals, list)
        signals.append("card_overdue")
        details = entry["details"]
        assert isinstance(details, dict)
        details["overdue_days"] = f"{overdue_days}"
        entry["review_card_id"] = card.id

    for lid, count in tutor_counts.items():
        if count < TUTOR_REPEAT_THRESHOLD:
            continue
        entry = accum[lid]
        entry["weight"] = int(entry["weight"]) + max(1, count // TUTOR_REPEAT_THRESHOLD)
        signals = entry["signals"]
        assert isinstance(signals, list)
        signals.append("tutor_repeat")
        details = entry["details"]
        assert isinstance(details, dict)
        details["tutor_count"] = f"{count}"
        # If a tutor-only weak spot also has an overdue card we already
        # stamped the card id above; otherwise the queue link still
        # points at the FSRS surface but with no specific card to pre-
        # select — that's the API consumer's call.

    candidates = list(accum.items())
    if not candidates:
        return []

    # Resolve lesson + course context in one shot; drops any lesson
    # whose row no longer exists (soft-deleted) so we don't surface
    # ghost weak spots.
    lessons = await _lessons_by_id(db, [lid for lid, _ in candidates])
    rows: list[tuple[int, WeakSpot]] = []
    for lid, entry in candidates:
        meta = lessons.get(lid)
        if meta is None:
            continue
        weight = int(entry["weight"])
        if weight <= 0:
            continue
        signals = entry["signals"]
        assert isinstance(signals, list)
        details = entry["details"]
        assert isinstance(details, dict)
        # Re-sort signals by the canonical priority order so the UI
        # always reads strongest-first regardless of insertion order.
        priority = {
            "quiz_failed": 0,
            "card_overdue": 1,
            "quiz_low": 2,
            "tutor_repeat": 3,
        }
        signals_typed: list[str] = [str(s) for s in signals]
        signals_typed.sort(key=lambda s: priority.get(s, 99))
        details_typed: dict[str, str] = {str(k): str(v) for k, v in details.items()}
        rcid = entry["review_card_id"]
        rows.append(
            (
                weight,
                WeakSpot(
                    lesson=meta,
                    signals=signals_typed,
                    signal_details=details_typed,
                    review_card_id=str(rcid) if rcid else None,
                ),
            )
        )

    rows.sort(key=lambda t: (-t[0], t[1].lesson.title))
    return [r for _, r in rows[:limit]]


async def per_course_mastery(db: AsyncSession, user_id: str) -> list[CourseMastery]:
    """Per-enrolled-course mastery + completion rollups.

    For each enrollment:

    * ``completion_pct`` = completed-lesson-count / total-lesson-count
      (counts soft-deletes out of both sides, same as the dashboard).
    * ``mastery_pct`` = average of the latest quiz attempt score across
      every quiz lesson in the course the learner has *attempted*. If
      the learner hasn't attempted any quizzes in the course yet the
      value is 0.0 — the UI surface differentiates "no attempts" from
      "attempted and failed" via the completion bar.

    Returns rows ordered by enrollment created_at desc (newest first),
    matching the dashboard's enrollment list ordering so the two
    surfaces feel like the same data.
    """
    # Pull live enrollments for the learner (mirrors what the dashboard
    # already does — we deliberately read off the same view so the
    # mastery surface never lists a course the dashboard hides).
    res = await db.execute(
        select(Enrollment, Course)
        .join(Course, Course.id == Enrollment.course_id)
        .where(Enrollment.user_id == user_id, Course.deleted_at.is_(None))
        .order_by(Enrollment.created_at.desc())
    )
    rows = list(res.all())
    if not rows:
        return []

    course_ids = [c.id for _, c in rows]
    enrollment_ids = [e.id for e, _ in rows]

    # Lessons-per-course (live), one shot.
    lessons_res = await db.execute(
        select(Module.course_id, func.count(Lesson.id))
        .join(Lesson, Lesson.module_id == Module.id)
        .where(
            Module.course_id.in_(course_ids),
            Lesson.deleted_at.is_(None),
        )
        .group_by(Module.course_id)
    )
    lesson_totals = {row[0]: int(row[1]) for row in lessons_res.all()}

    # Completed-lessons-per-enrollment (live), one shot.
    done_res = await db.execute(
        select(LessonProgress.enrollment_id, func.count(LessonProgress.id))
        .join(Lesson, Lesson.id == LessonProgress.lesson_id)
        .where(
            LessonProgress.enrollment_id.in_(enrollment_ids),
            LessonProgress.completed_at.is_not(None),
            Lesson.deleted_at.is_(None),
        )
        .group_by(LessonProgress.enrollment_id)
    )
    done_counts = {row[0]: int(row[1]) for row in done_res.all()}

    # Latest quiz-attempt score per (enrollment, lesson). Same row_number
    # trick as ``_latest_quiz_score_per_lesson`` but partitioned by
    # enrollment so we can roll up by course.
    rn = (
        func.row_number()
        .over(
            partition_by=(QuizAttempt.enrollment_id, QuizAttempt.lesson_id),
            order_by=QuizAttempt.submitted_at.desc(),
        )
        .label("rn")
    )
    inner = (
        select(
            QuizAttempt.enrollment_id,
            QuizAttempt.score,
            rn,
        )
        .where(QuizAttempt.enrollment_id.in_(enrollment_ids))
        .subquery()
    )
    avg_res = await db.execute(
        select(
            inner.c.enrollment_id,
            func.avg(inner.c.score).label("avg_score"),
            func.count(inner.c.score).label("attempt_count"),
        )
        .where(inner.c.rn == 1)
        .group_by(inner.c.enrollment_id)
    )
    avg_scores: dict[str, tuple[float, int]] = {
        row.enrollment_id: (float(row.avg_score or 0.0), int(row.attempt_count or 0))
        for row in avg_res.all()
    }

    out: list[CourseMastery] = []
    for enr, course in rows:
        total = lesson_totals.get(course.id, 0)
        done = done_counts.get(enr.id, 0)
        completion = round((done / total * 100.0) if total else 0.0, 1)

        avg, count = avg_scores.get(enr.id, (0.0, 0))
        # No quiz attempts at all → 0.0, signalled to the UI via the
        # ``mastery_pct == 0 and completion_pct > 0`` combination
        # (don't penalise a course that's all text lessons).
        mastery = round(avg, 1) if count else 0.0

        out.append(
            CourseMastery(
                course_id=course.id,
                slug=course.slug,
                title=course.title,
                mastery_pct=mastery,
                completion_pct=completion,
            )
        )
    return out


__all__ = [
    "CARD_OVERDUE_DAYS",
    "DEFAULT_WEAK_SPOT_LIMIT",
    "QUIZ_WEAK_SCORE",
    "TUTOR_REPEAT_THRESHOLD",
    "CourseMastery",
    "WeakSpot",
    "WeakSpotLesson",
    "per_course_mastery",
    "weak_spots",
]
