"""Self-critique authoring orchestrator tests (Lumen v2 Phase I3).

Exercises the researcher → outliner → critic ↺ reviser →
lesson-drafter → final-critic flow end-to-end against a scripted
LLM provider. The catalog is real (seeded in the test DB); Tavily
is disabled (no key set) so the researcher's web phase is a graceful
no-op. The only mocked seam is the LLM provider.

Coverage:

* Happy path: critic scores high on the first pass; no revision.
* Critic-low triggers a reviser turn; the second critic pass
  accepts; the trace records ``revision_number=1``.
* Revisions cap at :data:`MAX_REVISIONS`; the orchestrator stops
  after 3 revisions even if the critic still says "low."
* Final critic always runs; result carries its score + rationale.
* Subject-slug not found → :class:`NotFoundError` BEFORE any
  LLM call lands (so no tokens are burned on missing setup).
* Outliner double-failure → :class:`AppError` with the
  ``authoring.outliner_failed`` code.
* Trace rows land in step-index order with the right step kinds.

FR-DEFINE-18 (conscious pinned-test update for S3.6 / DR-4): the public
brief-driven entry point ``draft_course`` now takes a finalized ``brief_id`` and
derives difficulty/outcomes/estimate from the brief (those NEW behaviours are
pinned in ``test_authoring_brief_constraints.py``). The legacy raw-paragraph
instructor path — which these tests exercise — moved to
``draft_course_from_text``, which preserves the pre-S3 contract verbatim
(``Difficulty.beginner`` default + ``authoring.subject_not_found`` on a missing
slug). We deliberately repoint every call here to ``draft_course_from_text``
rather than weaken an assertion: the legacy pipeline behaviour is unchanged; only
its name and the new brief-driven sibling differ.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.models.course import (
    Course,
    CourseStatus,
    Subject,
)
from app.models.course_draft_trace import (
    DRAFT_STATUS_OK,
    DRAFT_STEP_CRITIC,
    DRAFT_STEP_FINAL_CRITIC,
    DRAFT_STEP_LESSON_DRAFTER,
    DRAFT_STEP_OUTLINER,
    DRAFT_STEP_RESEARCHER,
    DRAFT_STEP_REVISER,
    CourseDraftTrace,
)
from app.models.user import Role
from app.services import authoring_orchestrator
from app.services import llm as llm_service

# ---------- Scripted provider ----------


class _ScriptedProvider:
    """Plays back a canned queue of LLM replies.

    Same shape as the I5 scripted provider — supports both
    ``chat`` and ``chat_with_usage`` so :func:`call_logged`'s
    metered path works without monkeypatching the cost meter.
    """

    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[llm_service.ChatMessage]] = []

    async def chat(self, messages, temperature: float = 0.2) -> str:
        del temperature
        self.calls.append(list(messages))
        if not self._replies:
            raise AssertionError("ScriptedProvider queue exhausted — test under-scripted the LLM.")
        return self._replies.pop(0)

    async def chat_with_usage(self, messages, temperature: float = 0.2):
        text = await self.chat(messages, temperature=temperature)
        return llm_service.ChatResponse(
            text=text,
            prompt_tokens=64,
            completion_tokens=64,
            model=self._model,
        )


@pytest.fixture(autouse=True)
def _pin_env(monkeypatch):
    """Pin env so Tavily is disabled + cost-tracking is on but generous."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _install_provider(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    # Patch in the modules that import ``get_provider`` directly so
    # the orchestrator + the existing ai_authoring helpers both use
    # the scripted provider.
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    from app.services import authoring_orchestrator as orch_mod

    monkeypatch.setattr(orch_mod.llm_service, "get_provider", lambda: prov)
    from app.services import ai_authoring as ai_mod

    monkeypatch.setattr(ai_mod.llm_service, "get_provider", lambda: prov)
    return prov


# ---------- Fixtures: subject + outline templates ----------


async def _make_subject(db: AsyncSession) -> Subject:
    """Create a unique subject row + commit it for the orchestrator to find."""
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"Programming {suffix}", slug=f"prog-{suffix}")
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject


_VALID_OUTLINE = {
    "title": "FastAPI in 90 Minutes",
    "overview": "A focused intro to building APIs with FastAPI.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [
                {"title": "Install Python 3.13", "type": "text"},
                {"title": "Install FastAPI", "type": "text"},
                {"title": "Setup quiz", "type": "quiz"},
            ],
        },
        {
            "title": "First endpoint",
            "lessons": [
                {"title": "Hello world endpoint", "type": "text"},
                {"title": "Endpoint quiz", "type": "quiz"},
            ],
        },
    ],
}


_REVISED_OUTLINE = {
    "title": "FastAPI in 90 Minutes — revised",
    "overview": "A revised intro to building APIs with FastAPI.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [
                {"title": "Install Python 3.13", "type": "text"},
                {"title": "Install FastAPI", "type": "text"},
                {"title": "Setup quiz", "type": "quiz"},
            ],
        },
        {
            "title": "First endpoint with type safety",
            "lessons": [
                {"title": "Hello world endpoint", "type": "text"},
                {"title": "Pydantic models", "type": "text"},
                {"title": "Endpoint quiz", "type": "quiz"},
            ],
        },
    ],
}


def _critic_json(
    *, coverage: int, learning_arc: int, scope: int, weak_spots=None, rationale="ok"
) -> str:
    return json.dumps(
        {
            "scores": {
                "coverage": coverage,
                "learning_arc": learning_arc,
                "scope": scope,
            },
            "weak_spots": weak_spots or [],
            "rationale": rationale,
        }
    )


_VALID_LESSON_DOC = json.dumps(
    {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Overview"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Body text here."}],
            },
        ],
    }
)


_VALID_QUIZ_JSON = json.dumps(
    {
        "questions": [
            {
                "id": "q1",
                "prompt": "What is FastAPI?",
                "kind": "single",
                "choices": [
                    {"id": "a", "text": "A Python framework"},
                    {"id": "b", "text": "A database"},
                ],
                "answer_keys": ["a"],
            }
        ]
    }
)


def _lesson_drafter_replies(outline: dict) -> list[str]:
    """Build the per-lesson queue: one body JSON or quiz JSON per lesson."""
    out: list[str] = []
    for m in outline["modules"]:
        for lesson in m["lessons"]:
            if lesson["type"] == "quiz":
                out.append(_VALID_QUIZ_JSON)
            else:
                out.append(_VALID_LESSON_DOC)
    return out


# ---------- Happy path ----------


async def test_draft_course_happy_path_no_revisions(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """First critic accepts the outline; no reviser fires."""
    user = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    # Queue: outliner → critic (accepts) → N × lesson-drafter → final-critic.
    replies = [
        json.dumps(_VALID_OUTLINE),
        _critic_json(coverage=5, learning_arc=5, scope=5),
        *_lesson_drafter_replies(_VALID_OUTLINE),
        _critic_json(coverage=4, learning_arc=4, scope=4, rationale="ready"),
    ]
    _install_provider(monkeypatch, replies)

    result = await authoring_orchestrator.draft_course_from_text(
        db_session,
        user=user,
        brief="Teach FastAPI to absolute beginners.",
        subject_slug=subject.slug,
    )

    assert result.revisions_used == 0
    assert result.module_count == 2
    assert result.lesson_count == 5
    assert result.final_score.coverage == 4
    assert result.final_rationale == "ready"
    assert result.draft_id  # non-empty string

    # Course landed as a draft.
    course = await db_session.get(Course, result.course_id)
    assert course is not None
    assert course.status == CourseStatus.draft
    assert course.owner_id == user.id
    assert course.subject_id == subject.id

    # Traces: researcher + outliner + critic + N × lesson-drafter + final.
    traces = (
        (
            await db_session.execute(
                select(CourseDraftTrace)
                .where(CourseDraftTrace.draft_id == result.draft_id)
                .order_by(CourseDraftTrace.step_index.asc())
            )
        )
        .scalars()
        .all()
    )
    kinds = [t.step for t in traces]
    assert kinds[0] == DRAFT_STEP_RESEARCHER
    assert kinds[1] == DRAFT_STEP_OUTLINER
    assert kinds[2] == DRAFT_STEP_CRITIC
    assert kinds[-1] == DRAFT_STEP_FINAL_CRITIC
    # Lesson-drafter rows in the middle (one per lesson).
    lesson_drafter_rows = [t for t in traces if t.step == DRAFT_STEP_LESSON_DRAFTER]
    assert len(lesson_drafter_rows) == 5
    # No reviser row.
    assert not any(t.step == DRAFT_STEP_REVISER for t in traces)
    # All ok.
    assert all(t.status == DRAFT_STATUS_OK for t in traces)
    # Course id back-filled on every row.
    assert all(t.course_id == course.id for t in traces)


# ---------- Critic-low triggers a revision ----------


async def test_critic_low_triggers_reviser(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A low critic score on the first pass fires the reviser."""
    user = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    replies = [
        json.dumps(_VALID_OUTLINE),  # outliner
        _critic_json(coverage=2, learning_arc=3, scope=3, weak_spots=["lack of depth"]),
        json.dumps(_REVISED_OUTLINE),  # reviser
        _critic_json(coverage=5, learning_arc=5, scope=4),  # accepts revised
        *_lesson_drafter_replies(_REVISED_OUTLINE),
        _critic_json(coverage=4, learning_arc=4, scope=4),  # final
    ]
    _install_provider(monkeypatch, replies)

    result = await authoring_orchestrator.draft_course_from_text(
        db_session,
        user=user,
        brief="Teach FastAPI with depth.",
        subject_slug=subject.slug,
    )
    assert result.revisions_used == 1
    assert result.lesson_count == 6  # _REVISED_OUTLINE has 6 lessons

    # Trace: reviser row present, with revision_number=1.
    traces = (
        (
            await db_session.execute(
                select(CourseDraftTrace)
                .where(CourseDraftTrace.draft_id == result.draft_id)
                .order_by(CourseDraftTrace.step_index.asc())
            )
        )
        .scalars()
        .all()
    )
    reviser_rows = [t for t in traces if t.step == DRAFT_STEP_REVISER]
    assert len(reviser_rows) == 1
    assert reviser_rows[0].payload.get("revision_number") == 1


# ---------- Revisions cap at MAX_REVISIONS ----------


async def test_revisions_cap_at_max(db_session: AsyncSession, make_user, monkeypatch) -> None:
    """Even with critic always-low replies, revisions stop at 3."""
    user = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    # Pathological queue: critic always says 2/2/2; we exhaust the
    # outline phase budget. After ``MAX_OUTLINE_PHASE_LLM_CALLS = 6``
    # the loop stops and accepts whatever outline we last had.
    # Sequence: outliner (1), critic (2), reviser (3), critic (4),
    # reviser (5), critic (6) → cap hit; drafter + final follow.
    always_low = _critic_json(coverage=2, learning_arc=2, scope=2, weak_spots=["x"])
    replies = [
        json.dumps(_VALID_OUTLINE),  # outliner — call 1
        always_low,  # critic — call 2
        json.dumps(_REVISED_OUTLINE),  # reviser — call 3
        always_low,  # critic — call 4
        json.dumps(_REVISED_OUTLINE),  # reviser — call 5
        always_low,  # critic — call 6 (cap reached)
        # Lesson-drafter + final.
        *_lesson_drafter_replies(_REVISED_OUTLINE),
        _critic_json(coverage=3, learning_arc=3, scope=3),  # final
    ]
    _install_provider(monkeypatch, replies)

    result = await authoring_orchestrator.draft_course_from_text(
        db_session,
        user=user,
        brief="Stubborn brief.",
        subject_slug=subject.slug,
    )
    # The reviser ran twice before the cap fired.
    assert result.revisions_used <= authoring_orchestrator.MAX_REVISIONS

    traces = (
        (
            await db_session.execute(
                select(CourseDraftTrace)
                .where(CourseDraftTrace.draft_id == result.draft_id)
                .order_by(CourseDraftTrace.step_index.asc())
            )
        )
        .scalars()
        .all()
    )
    reviser_rows = [t for t in traces if t.step == DRAFT_STEP_REVISER]
    # At most MAX_REVISIONS reviser rows.
    assert len(reviser_rows) <= authoring_orchestrator.MAX_REVISIONS


# ---------- Unknown subject ----------


async def test_unknown_subject_raises_before_llm(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Missing subject_slug bails before burning any LLM tokens."""
    user = await make_user(role=Role.instructor)
    prov = _install_provider(monkeypatch, [])  # empty — must not be called

    with pytest.raises(NotFoundError) as exc:
        await authoring_orchestrator.draft_course_from_text(
            db_session,
            user=user,
            brief="Teach FastAPI.",
            subject_slug="does-not-exist",
        )
    assert exc.value.code == "authoring.subject_not_found"
    assert prov.calls == []  # no LLM call landed


# ---------- Outliner double-failure ----------


async def test_outliner_double_failure_raises(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Two bad outliner replies → AppError, no course created."""
    user = await make_user(role=Role.instructor)
    subject = await _make_subject(db_session)

    _install_provider(monkeypatch, ["not json", "still not json"])
    with pytest.raises(AppError) as exc:
        await authoring_orchestrator.draft_course_from_text(
            db_session,
            user=user,
            brief="Teach FastAPI.",
            subject_slug=subject.slug,
        )
    assert exc.value.code == "authoring.outliner_failed"
    # No course landed.
    courses = (
        (await db_session.execute(select(Course).where(Course.owner_id == user.id))).scalars().all()
    )
    assert courses == []


# ---------- Schemas ----------


def test_critic_scores_mean_property() -> None:
    """Mean is the arithmetic average — pin so refactors don't drift."""
    s = authoring_orchestrator.CriticScores(coverage=4, learning_arc=3, scope=5)
    assert s.mean == 4.0
    s2 = authoring_orchestrator.CriticScores(coverage=5, learning_arc=5, scope=5)
    assert s2.mean == 5.0


def test_critic_scores_reject_out_of_range() -> None:
    """Each axis is 0-5 inclusive — out-of-range is a validation error."""
    with pytest.raises(Exception):
        authoring_orchestrator.CriticScores(coverage=6, learning_arc=3, scope=3)
