"""S3.6 / DR-4 / FR-DEFINE-04/11/12/16/18 — brief→``draft_course`` plumbing.

Exercises the finalized-brief-driven build: difficulty from ``brief.level``,
learning_outcomes from the brief, module-count band from ``time_budget_hours``,
constraint lines in the outliner + critic prompts, subject auto-resolution to the
reserved Personal subject, and ``visibility=private`` on the built course. These
are the NEW behaviours DR-4 adds; the conscious update to the legacy pinned tests
lives in ``test_authoring_orchestrator.py`` (FR-DEFINE-18).

The LLM provider is the same scripted seam the orchestrator tests use. The brief
is a real finalized ``LearningBrief`` row (the goal is field-encrypted at rest).
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import AppError
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Subject,
    Visibility,
)
from app.models.learning_brief import LearningBrief
from app.models.user import Role
from app.services import authoring_orchestrator
from app.services import llm as llm_service

# ---------- Scripted provider (mirrors test_authoring_orchestrator.py) ----------


class _ScriptedProvider:
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
            text=text, prompt_tokens=64, completion_tokens=64, model=self._model
        )

    def rendered_text(self) -> str:
        """All system+user content the model ever saw, concatenated."""
        return "\n".join(m.content for call in self.calls for m in call)


@pytest.fixture(autouse=True)
def _pin_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _install_provider(monkeypatch, replies: list[str]) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    from app.services import authoring_orchestrator as orch_mod

    monkeypatch.setattr(orch_mod.llm_service, "get_provider", lambda: prov)
    from app.services import ai_authoring as ai_mod

    monkeypatch.setattr(ai_mod.llm_service, "get_provider", lambda: prov)
    return prov


# ---------- Brief fixtures ----------


async def _make_personal_subject(db: AsyncSession) -> Subject:
    """Create (idempotently) the reserved Personal subject the seed installs."""
    slug = get_settings().personal_subject_slug
    from app.repositories import courses as courses_repo

    existing = await courses_repo.get_subject_by_slug(db, slug)
    if existing is not None:
        return existing
    subject = Subject(title="Personal / Self-directed", slug=slug)
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return subject


async def _finalized_brief(
    db: AsyncSession,
    *,
    owner_id: str,
    goal: str = "I want to get good at React.",
    level: str | None = "advanced",
    time_budget_hours: int | None = 30,
    prior_knowledge: str = "I know JS well.",
    desired_outcomes: list[str] | None = None,
    suggested_subject: str | None = None,
    finalized: bool = True,
) -> LearningBrief:
    from datetime import UTC, datetime

    brief = LearningBrief(
        owner_id=owner_id,
        source_goal_enc=secrets_crypto.encrypt(goal.encode("utf-8")),
        goal_summary="Learn React deeply.",
        level=level,
        prior_knowledge=prior_knowledge,
        time_budget_hours=time_budget_hours,
        desired_outcomes=desired_outcomes or ["Build a SPA", "Use hooks"],
        suggested_subject=suggested_subject,
        finalized_at=datetime.now(UTC) if finalized else None,
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


_OUTLINE = {
    "title": "React Deep Dive",
    "overview": "A focused, advanced React course.",
    "modules": [
        {
            "title": "Hooks",
            "lessons": [
                {"title": "useState", "type": "text"},
                {"title": "Hooks quiz", "type": "quiz"},
            ],
        },
    ],
}


def _critic(coverage=5, learning_arc=5, scope=5) -> str:
    return json.dumps(
        {
            "scores": {"coverage": coverage, "learning_arc": learning_arc, "scope": scope},
            "weak_spots": [],
            "rationale": "ok",
        }
    )


_LESSON_DOC = json.dumps(
    {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Body."}]}],
    }
)
_QUIZ_JSON = json.dumps(
    {
        "questions": [
            {
                "id": "q1",
                "prompt": "Q?",
                "kind": "single",
                "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "answer_keys": ["a"],
            }
        ]
    }
)


def _drafter_replies(outline: dict) -> list[str]:
    out: list[str] = []
    for m in outline["modules"]:
        for lesson in m["lessons"]:
            out.append(_QUIZ_JSON if lesson["type"] == "quiz" else _LESSON_DOC)
    return out


def _happy_queue(outline: dict = _OUTLINE) -> list[str]:
    return [
        json.dumps(outline),
        _critic(),
        *_drafter_replies(outline),
        _critic(coverage=4, learning_arc=4, scope=4),
    ]


# ---------- DR-4: difficulty from level ----------


async def test_difficulty_derived_from_brief_level(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """``level=advanced`` → ``Difficulty.advanced`` (NOT the old beginner hardcode)."""
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id, level="advanced")
    _install_provider(monkeypatch, _happy_queue())

    result = await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    course = await db_session.get(Course, result.course_id)
    assert course is not None
    assert course.difficulty == Difficulty.advanced


# ---------- FR-DEFINE-04b: outcomes from the brief ----------


async def test_learning_outcomes_from_brief(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    outcomes = ["Ship a production SPA", "Reason about reconciliation"]
    brief = await _finalized_brief(db_session, owner_id=user.id, desired_outcomes=outcomes)
    _install_provider(monkeypatch, _happy_queue())

    result = await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    course = await db_session.get(Course, result.course_id)
    assert course is not None
    assert list(course.learning_outcomes) == outcomes


# ---------- FR-DEFINE-16 / DR-4: module estimate from the time budget ----------


@pytest.mark.parametrize(
    "hours,low,high",
    [
        (4, 2, 3),  # <=5h → low band
        (12, 3, 5),  # 6-20h → mid band
        (40, 5, 8),  # >20h → high band
    ],
)
async def test_module_estimate_band_in_prompt(
    db_session: AsyncSession, make_user, monkeypatch, hours, low, high
) -> None:
    """The outliner prompt carries the budget-derived module-count target band."""
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id, time_budget_hours=hours)
    prov = _install_provider(monkeypatch, _happy_queue())

    await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    rendered = prov.rendered_text()
    # The estimate is the band midpoint count; the prompt must reference the hours.
    assert f"{hours}" in rendered
    # Module-count target token present (the deterministic estimate).
    from app.services.learning_brief import estimate_counts

    target_modules, _ = estimate_counts(hours)
    assert low <= target_modules <= high
    assert str(target_modules) in rendered


# ---------- DR-4: level + outcomes constraint lines in outliner AND critic ----------


async def test_outliner_and_critic_prompts_carry_constraints(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    brief = await _finalized_brief(
        db_session,
        owner_id=user.id,
        level="advanced",
        time_budget_hours=30,
        desired_outcomes=["Master suspense boundaries"],
    )
    prov = _install_provider(monkeypatch, _happy_queue())

    await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    rendered = prov.rendered_text()
    assert "advanced" in rendered  # target level
    assert "30" in rendered  # time budget hours
    assert "Master suspense boundaries" in rendered  # required outcome


# ---------- FR-DEFINE-12: subject auto-resolution to Personal ----------


async def test_subject_auto_resolves_to_personal_when_no_match(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A suggested subject matching no live Subject attaches to personal-self-directed,
    NEVER raising authoring.subject_not_found."""
    user = await make_user(role=Role.instructor)
    personal = await _make_personal_subject(db_session)
    brief = await _finalized_brief(
        db_session, owner_id=user.id, suggested_subject="Quantum Basket Weaving"
    )
    _install_provider(monkeypatch, _happy_queue())

    result = await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    course = await db_session.get(Course, result.course_id)
    assert course is not None
    assert course.subject_id == personal.id


async def test_subject_matches_live_subject_by_slug(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A suggested subject that DOES match a live Subject (by slug) uses it."""
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    suffix = uuid.uuid4().hex[:6]
    real = Subject(title=f"Web Dev {suffix}", slug=f"web-dev-{suffix}")
    db_session.add(real)
    await db_session.commit()
    await db_session.refresh(real)
    brief = await _finalized_brief(db_session, owner_id=user.id, suggested_subject=real.slug)
    _install_provider(monkeypatch, _happy_queue())

    result = await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    course = await db_session.get(Course, result.course_id)
    assert course is not None
    assert course.subject_id == real.id


# ---------- FR-DEFINE-11: private draft ----------


async def test_built_course_is_private_draft(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    _install_provider(monkeypatch, _happy_queue())

    result = await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    course = await db_session.get(Course, result.course_id)
    assert course is not None
    assert course.visibility == Visibility.private
    assert course.status == CourseStatus.draft


# ---------- FR-DEFINE-07: an un-finalized brief cannot build ----------


async def test_unfinalized_brief_rejected(db_session: AsyncSession, make_user, monkeypatch) -> None:
    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id, finalized=False)
    prov = _install_provider(monkeypatch, [])  # must not be called

    with pytest.raises(AppError) as exc:
        await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    assert exc.value.code == "define.brief_not_finalized"
    assert prov.calls == []  # no LLM tokens burned


# ---------- FR-PRIV-01: the raw goal never lands in a trace summary ----------


async def test_raw_goal_not_in_trace_summary(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """The decrypted goal lives only in the prompt builder — trace summaries use
    the non-sensitive goal_summary, never the raw goal text."""
    from sqlalchemy import select

    from app.models.course_draft_trace import CourseDraftTrace

    user = await make_user(role=Role.instructor)
    await _make_personal_subject(db_session)
    secret_goal = "SECRET_GOAL_TOKEN_xyzzy please don't leak me"
    brief = await _finalized_brief(db_session, owner_id=user.id, goal=secret_goal)
    _install_provider(monkeypatch, _happy_queue())

    result = await authoring_orchestrator.draft_course(db_session, user=user, brief_id=brief.id)
    traces = (
        (
            await db_session.execute(
                select(CourseDraftTrace).where(CourseDraftTrace.draft_id == result.draft_id)
            )
        )
        .scalars()
        .all()
    )
    blob = json.dumps([dict(t.payload or {}) for t in traces])
    assert "xyzzy" not in blob
    assert secret_goal not in blob
