"""Per-learner mastery dashboard endpoint.

Rebuild Phase E7. One endpoint, ``GET /api/v1/me/mastery``, returns
the bundled payload the frontend needs to render the mastery surface:

* a ranked list of *weak spots* — actionable lessons the learner
  should revisit, each with the reasons (signal codes + numeric
  details) it's flagged;
* a per-enrolled-course row with two percentages — completion (how
  much of the course they've finished) and mastery (the average of
  their latest quiz scores).

Both pieces are returned in a single round-trip rather than as two
endpoints because the dashboard renders them together; splitting
them would mean the surface either flashes between two loading states
or has to await both spinners before painting anything. The service
layer already runs the underlying queries in parallel-ish order (each
``await`` is a single round-trip), so there's no per-bundle cost over
two separate endpoints — but there's a real UX win.

Rate-limited at 60/minute per identity. The endpoint isn't write-
heavy but it does fan out into a handful of SELECTs (latest-quiz-per-
lesson with a window function, overdue-cards, tutor-citation
aggregation, plus the per-course rollups); 60/min is roughly 1/second,
well above any plausible interactive use and still leaves us a safe
margin against a misbehaving client that polls in a tight loop.

The response envelope is intentionally flat:

    {
      "weak_spots": [
        {
          "lesson": {id, title, course_id, course_slug, course_title},
          "signals": ["quiz_failed", "card_overdue", ...],
          "signal_details": {"quiz_score": "55", "overdue_days": "3", ...},
          "review_card_id": "rc_..." | null
        },
        ...
      ],
      "courses": [
        {"course_id", "slug", "title", "mastery_pct", "completion_pct"},
        ...
      ]
    }

The signal codes are stable strings the frontend translates and
chooses pill variants from; the details map is open-ended so future
signals can add fields without a schema bump.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.core.ratelimit import limiter
from app.services import mastery as mastery_service

router = APIRouter()


# ---------- response shapes ----------


class WeakSpotLessonOut(BaseModel):
    """Slimmed lesson + course context attached to a weak-spot row."""

    id: str
    title: str
    course_id: str
    course_slug: str
    course_title: str


class WeakSpotOut(BaseModel):
    """One row in the actionable weak-spot list."""

    lesson: WeakSpotLessonOut
    signals: list[str] = Field(
        description=(
            "Stable signal codes ordered strongest-first. Known codes: "
            "``quiz_failed``, ``card_overdue``, ``quiz_low``, "
            "``tutor_repeat``. The frontend localises each code and "
            "chooses a pill variant from it."
        )
    )
    signal_details: dict[str, str] = Field(
        description=(
            "Open-ended numeric context for each signal: "
            "``{quiz_score, overdue_days, tutor_count}``. All values "
            "are pre-stringified so the JSON shape stays uniform."
        )
    )
    review_card_id: str | None = Field(
        default=None,
        description=(
            "If the lesson has an FSRS card currently due/overdue, the "
            "frontend's 'Review now' CTA deep-links into the spaced-"
            "repetition queue. Null when the weak spot only originates "
            "from quizzes or tutor signals."
        ),
    )


class CourseMasteryOut(BaseModel):
    """Per-course rollup row on the mastery dashboard."""

    course_id: str
    slug: str
    title: str
    mastery_pct: float = Field(
        description=(
            "Average of the latest quiz-attempt score across every quiz "
            "lesson the learner has attempted in this course. 0.0 when "
            "the learner hasn't attempted any quizzes (the UI uses "
            "completion_pct to disambiguate 'never tried' from 'tried "
            "and failed everything')."
        )
    )
    completion_pct: float = Field(
        description=(
            "Fraction of live lessons in the course the learner has marked complete, 0.0-100.0."
        )
    )


class MasteryResponse(BaseModel):
    """Bundled mastery-dashboard payload."""

    weak_spots: list[WeakSpotOut]
    courses: list[CourseMasteryOut]


# ---------- endpoint ----------


@router.get("/mastery", response_model=MasteryResponse)
@limiter.limit("60/minute")
async def get_mastery(
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> MasteryResponse:
    """Return the bundled mastery dashboard for the calling learner.

    The endpoint scopes everything to the calling user — there's no
    way to read another learner's mastery (instructor analytics live
    on the course-scoped ``/courses/{id}/analytics`` surface, which
    aggregates differently). Returns 200 with empty lists for a
    learner who hasn't enrolled in anything yet so the frontend can
    render its empty-state directly.
    """
    spots = await mastery_service.weak_spots(db, user_id=user.id)
    courses = await mastery_service.per_course_mastery(db, user_id=user.id)
    return MasteryResponse(
        weak_spots=[
            WeakSpotOut(
                lesson=WeakSpotLessonOut(
                    id=s.lesson.id,
                    title=s.lesson.title,
                    course_id=s.lesson.course_id,
                    course_slug=s.lesson.course_slug,
                    course_title=s.lesson.course_title,
                ),
                signals=list(s.signals),
                signal_details=dict(s.signal_details),
                review_card_id=s.review_card_id,
            )
            for s in spots
        ],
        courses=[
            CourseMasteryOut(
                course_id=c.course_id,
                slug=c.slug,
                title=c.title,
                mastery_pct=c.mastery_pct,
                completion_pct=c.completion_pct,
            )
            for c in courses
        ],
    )
