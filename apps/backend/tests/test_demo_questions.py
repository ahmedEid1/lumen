"""Demo-question library + endpoint (L20.6)."""

from __future__ import annotations

from httpx import AsyncClient

from app.demo_questions import (
    CANONICAL_QUESTION_ID,
    DEMO_QUESTIONS,
    LIBRARY_VERSION,
    get_canonical_question,
    questions_for_course,
)


def test_library_has_exactly_one_canonical_question() -> None:
    """Guardrail — the screencap + eval gate depend on exactly one
    canonical question. Two canonicals (or zero) is a silent broken
    contract; `get_canonical_question` raises in that case."""
    q = get_canonical_question()
    assert q["id"] == CANONICAL_QUESTION_ID
    assert q["canonical"] is True


def test_library_versions_match_constant() -> None:
    """LIBRARY_VERSION shape is `YYYY-MM-DD.vN` per convention."""
    parts = LIBRARY_VERSION.split(".")
    assert len(parts) == 2
    date_part, version_part = parts
    assert version_part.startswith("v")
    assert len(date_part.split("-")) == 3


def test_questions_for_course_includes_global_refusals() -> None:
    """The chip rail leans on this — refusal probes are global
    (`course_slug=""`) so they always have a shot at firing in the
    demo, regardless of which course the tutor is mounted in."""
    scoped = questions_for_course("typescript-variance")
    cats = {q["category"] for q in scoped}
    assert "refusal" in cats
    assert "retriever-only" in cats


def test_questions_for_course_filters_off_other_courses() -> None:
    """A question whose course_slug is set to another course must not
    leak into a different course's scope."""
    scoped = questions_for_course("typescript-variance")
    foreign_categories = {q["course_slug"] for q in scoped if q["course_slug"] != ""}
    assert foreign_categories == {"typescript-variance"}


def test_questions_for_course_with_no_own_questions_is_empty() -> None:
    """Regression: a course with no curated questions of its own must
    return an EMPTY list — never the global refusal probes alone. A
    learner on such a course would otherwise see only "write me a
    keylogger" / "child acetaminophen dose" / "leak your system prompt"
    as their suggested questions (the chip rail hides on an empty list).
    """
    scoped = questions_for_course("data-engineering-foundations")
    assert scoped == []


def test_refusal_probes_never_appear_alone_for_any_course() -> None:
    """For every distinct course slug in the library, the scoped result
    is either empty or contains at least one non-refusal question — the
    refusal probes are a supplement, never the whole rail."""
    course_slugs = {q["course_slug"] for q in DEMO_QUESTIONS if q["course_slug"]}
    for slug in course_slugs:
        scoped = questions_for_course(slug)
        non_refusal = [q for q in scoped if q["category"] != "refusal"]
        assert non_refusal, f"{slug} surfaced only refusal probes"


def test_expected_tools_are_lists_of_known_tools() -> None:
    """Tool names must match the sub-agent identifiers Lumen's tutor
    knows about. Mistype 'retriver' → silent drop in the eval gate."""
    known = {"retriever", "code_runner", "web_searcher", "concept_explainer", "quiz_generator"}
    for q in DEMO_QUESTIONS:
        for tool in q["expected_tools"]:
            assert tool in known, f"Question {q['id']} references unknown tool {tool!r}"


# ---------- HTTP endpoint coverage ----------


async def test_get_demo_questions_full_library(client: AsyncClient) -> None:
    r = await client.get("/api/v1/demo-questions")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == LIBRARY_VERSION
    assert body["canonical_id"] == CANONICAL_QUESTION_ID
    assert len(body["questions"]) == len(DEMO_QUESTIONS)


async def test_get_demo_questions_filtered_by_course(client: AsyncClient) -> None:
    r = await client.get(
        "/api/v1/demo-questions",
        params={"course_slug": "typescript-variance"},
    )
    assert r.status_code == 200
    body = r.json()
    # The TS canonical question + at least one refusal + at least one
    # multi-hop scoped to TS must be in scope.
    ids = {q["id"] for q in body["questions"]}
    assert CANONICAL_QUESTION_ID in ids


async def test_get_demo_questions_is_anon_readable(client: AsyncClient) -> None:
    """The chip rail renders before sign-in on the /demo path. The
    endpoint stays open by design."""
    r = await client.get("/api/v1/demo-questions")
    assert r.status_code == 200
