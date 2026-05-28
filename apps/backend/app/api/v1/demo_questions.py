"""Demo-question library — public read-only endpoint (L20.6).

GET /api/v1/demo-questions?course_slug=<slug>

Returns the curated demo-question library scoped to a single course
(or, when course_slug is omitted, the full library). Consumed by the
L22 chip rail above the tutor composer.

Anon-readable on purpose — the chip rail renders before sign-in on
the /demo deep-link path. The questions themselves are not sensitive;
the only thing the endpoint exposes is a list of prompts the
maintainers picked as "good first questions."
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.demo_questions import (
    DEMO_QUESTIONS,
    LIBRARY_VERSION,
    DemoCategory,
    DemoQuestion,
    questions_for_course,
)

router = APIRouter()


class DemoQuestionOut(BaseModel):
    """Wire shape — matches the TypedDict in `app.demo_questions`."""

    model_config = ConfigDict(from_attributes=False)

    id: str
    category: DemoCategory
    prompt: str
    expected_tools: list[str]
    course_slug: str
    canonical: bool


class DemoQuestionLibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    version: str
    canonical_id: str
    questions: list[DemoQuestionOut]


def _to_wire(q: DemoQuestion) -> DemoQuestionOut:
    return DemoQuestionOut(
        id=q["id"],
        category=q["category"],
        prompt=q["prompt"],
        expected_tools=q["expected_tools"],
        course_slug=q["course_slug"],
        canonical=q["canonical"],
    )


@router.get(
    "/demo-questions",
    response_model=DemoQuestionLibraryOut,
    summary="Curated demo-question library",
    tags=["demo-questions"],
)
async def get_demo_questions(
    course_slug: str | None = Query(
        None,
        description=(
            "Optional course slug filter. When set, returns the course's own "
            "curated questions (a course with none returns an empty list). When "
            "unset, returns the full library. In BOTH cases the global "
            "adversarial refusal probes are excluded by default — they would "
            "otherwise read as jailbreak prompts framed as learner suggestions "
            "(see include_probes)."
        ),
    ),
    include_probes: bool = Query(
        False,
        description=(
            "When true, include the global adversarial refusal probes — "
            "course-scoped, they're appended to the course's own questions; "
            "unscoped, they're part of the full library. Off by default so the "
            "learner-facing chip rail never surfaces jailbreak prompts as "
            "suggestions; intended for the explicit guardrail-demo / audit flow "
            "(the methodology is documented at /eval/methodology)."
        ),
    ),
) -> DemoQuestionLibraryOut:
    if course_slug:
        questions = questions_for_course(course_slug, include_probes=include_probes)
    elif include_probes:
        questions = list(DEMO_QUESTIONS)
    else:
        # Unscoped default: full library minus the adversarial probes, so no
        # caller (incl. a slug-less chip-rail mount) ever gets jailbreak chips.
        questions = [q for q in DEMO_QUESTIONS if q["category"] != "refusal"]
    canonical = next((q for q in DEMO_QUESTIONS if q["canonical"]), None)
    return DemoQuestionLibraryOut(
        version=LIBRARY_VERSION,
        canonical_id=canonical["id"] if canonical else "",
        questions=[_to_wire(q) for q in questions],
    )
