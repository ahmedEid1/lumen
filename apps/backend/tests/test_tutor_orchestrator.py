"""Tutor orchestrator — planner + tools + re-plan + synthesiser (Phase I2).

Exercises the multi-agent flow end-to-end against a scripted LLM
provider. The catalog is real (seeded in the test DB, chunks
ingested); the LLM is the only mocked seam.

Coverage:

* Happy path: planner emits a single-tool ``retriever`` plan,
  synthesiser produces a cited answer, the trace records every
  step.
* Multi-tool plan: planner asks for ``retriever`` + ``quiz_generator``;
  both run, the synthesiser folds them, the tool-call summary lists
  both.
* Planner outage: malformed planner reply → fallback to single-tool
  retriever plan + the synthesiser still answers.
* Refusal projection: empty retrieval short-circuits before the
  orchestrator even runs (the ``tutor.ask`` wrapper handles this).
* Backwards compat: ``tutor.ask`` returns a ``TutorAnswer`` with the
  same shape Phase E1 tests pinned (refused / answer / citations).
* ``ask_with_trace`` returns both shapes — answer + orchestrator
  payload — for the chat-API surface.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent_trace import AgentTrace
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
)
from app.models.user import Role
from app.services import llm as llm_service
from app.services import tutor as tutor_service
from app.services import tutor_orchestrator
from app.services.embeddings_ingest import ingest_course


@pytest.fixture(autouse=True)
def _pin_providers(monkeypatch):
    """Pin embeddings + LLM to noop. Individual tests opt into scripted."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _uid() -> str:
    return f"u-{uuid.uuid4().hex[:16]}"


async def _seed_course(
    db: AsyncSession,
    *,
    owner_id: str,
    lesson_bodies: list[tuple[str, str]],
) -> Course:
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subject.id,
        title=f"Orch Test {suffix}",
        slug=f"orch-{suffix}",
        overview="overview",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
    )
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="M", order=0)
    db.add(module)
    await db.flush()
    for i, (title, body) in enumerate(lesson_bodies):
        db.add(
            Lesson(
                id=f"lsn_{suffix}_{i}",
                module_id=module.id,
                title=title,
                order=i,
                type=LessonType.text,
                data={"type": "text", "body_markdown": body},
            )
        )
    await db.commit()
    return course


class _ScriptedProvider:
    """Plays back a queue of canned LLM replies."""

    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[llm_service.ChatMessage]] = []

    async def chat(self, messages, temperature: float = 0.2) -> str:  # type: ignore[no-untyped-def]
        del temperature
        self.calls.append(list(messages))
        if not self._replies:
            raise AssertionError("scripted queue exhausted — test under-scripted the LLM")
        return self._replies.pop(0)

    async def chat_with_usage(self, messages, temperature: float = 0.2):  # type: ignore[no-untyped-def]
        text = await self.chat(messages, temperature=temperature)
        return llm_service.ChatResponse(
            text=text,
            prompt_tokens=64,
            completion_tokens=64,
            model=self._model,
        )


def _install_provider(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    return prov


# ---------- Plan / ToolCall schema sanity ----------


def test_plan_schema_rejects_unknown_tool_name() -> None:
    """Pydantic Literal validation gates ``tool_name`` to the five tools."""
    with pytest.raises(Exception):
        tutor_orchestrator.Plan.model_validate(
            {
                "tool_calls": [
                    {
                        "tool_name": "not_a_real_tool",
                        "args": {},
                        "rationale": "no.",
                    }
                ],
                "confidence_after_plan": 3,
            }
        )


def test_plan_schema_caps_tool_calls_at_three() -> None:
    """Planner is told to emit 1-3 tools; the model enforces that."""
    with pytest.raises(Exception):
        tutor_orchestrator.Plan.model_validate(
            {
                "tool_calls": [
                    {"tool_name": "retriever", "args": {}, "rationale": ""},
                    {"tool_name": "web_searcher", "args": {}, "rationale": ""},
                    {"tool_name": "code_runner", "args": {}, "rationale": ""},
                    {"tool_name": "quiz_generator", "args": {}, "rationale": ""},
                ],
                "confidence_after_plan": 3,
            }
        )


# ---------- End-to-end orchestrate ----------


async def test_orchestrate_happy_path_single_tool_retriever(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Planner picks retriever-only; synthesiser produces a cited answer."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[
            ("Photosynthesis", "Plants convert sunlight to sugar. " * 8),
            ("Respiration", "Cells produce ATP via respiration. " * 8),
        ],
    )
    await ingest_course(db_session, course.id)

    # Fetch the seeded lesson ids so we can script a synthesiser
    # reply that cites a real one.
    lessons = (await db_session.execute(select(Lesson).order_by(Lesson.order))).scalars().all()
    lid = lessons[0].id

    plan_reply = json.dumps(
        {
            "tool_calls": [
                {
                    "tool_name": "retriever",
                    "args": {"query": "How do plants make food?"},
                    "rationale": "Direct course-content lookup.",
                }
            ],
            "confidence_after_plan": 5,
            "final_answer_hint": None,
        }
    )
    synth_reply = f"Plants use chlorophyll to convert sunlight into sugar [L:{lid}]."
    # confidence_after_plan=5 so re-plan is skipped → only planner + synth.
    _install_provider(monkeypatch, [plan_reply, synth_reply])

    result = await tutor_orchestrator.orchestrate(
        db_session,
        user_id=_uid(),
        course=course,
        question="How do plants make food?",
    )
    assert not result.refused
    assert "chlorophyll" in result.answer
    assert lid in result.citations
    # Exactly one tool call landed (retriever).
    assert len(result.tool_calls_made) == 1
    assert result.tool_calls_made[0].tool_name == "retriever"


async def test_orchestrate_multi_tool_plan_runs_both(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A 2-tool plan dispatches retriever + quiz_generator; both run."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[("Cells", "Cells are the basic unit of life. " * 8)],
    )
    await ingest_course(db_session, course.id)

    lid = (await db_session.execute(select(Lesson.id))).scalar_one()

    plan_reply = json.dumps(
        {
            "tool_calls": [
                {
                    "tool_name": "retriever",
                    "args": {"query": "cell biology"},
                    "rationale": "Anchor on course content.",
                },
                {
                    "tool_name": "quiz_generator",
                    "args": {"topic": "cells"},
                    "rationale": "User asked for a practice question.",
                },
            ],
            "confidence_after_plan": 5,
            "final_answer_hint": None,
        }
    )
    quiz_reply = json.dumps(
        {
            "prompt": "What's the basic unit of life?",
            "options": ["Atom", "Cell", "Organ", "Molecule"],
            "answer_index": 1,
            "explanation": "Cells are the structural unit of all known life.",
        }
    )
    synth_reply = (
        f"Cells are the basic unit of life [L:{lid}]. "
        "Try this practice question: What's the basic unit of life?"
    )
    _install_provider(monkeypatch, [plan_reply, quiz_reply, synth_reply])

    result = await tutor_orchestrator.orchestrate(
        db_session,
        user_id=_uid(),
        course=course,
        question="Give me a practice question on cells.",
    )
    tool_names = [tc.tool_name for tc in result.tool_calls_made]
    assert "retriever" in tool_names
    assert "quiz_generator" in tool_names
    assert lid in result.citations


async def test_orchestrate_planner_failure_falls_back_to_retriever(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Malformed planner reply → single-tool retriever fallback + valid answer."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[("Intro", "An intro to cells. " * 8)],
    )
    await ingest_course(db_session, course.id)

    lid = (await db_session.execute(select(Lesson.id))).scalar_one()

    # Planner reply: complete garbage → fallback fires.
    # Synthesiser reply (1 LLM call after fallback retriever): valid.
    _install_provider(
        monkeypatch,
        [
            "no JSON here, just chatter",
            f"From the course, cells are foundational [L:{lid}].",
        ],
    )

    result = await tutor_orchestrator.orchestrate(
        db_session,
        user_id=_uid(),
        course=course,
        question="What is a cell?",
    )
    assert not result.refused
    assert lid in result.citations
    # Fallback plan = retriever only.
    assert [tc.tool_name for tc in result.tool_calls_made] == ["retriever"]


async def test_orchestrate_records_trace_steps(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Every plan / tool_call / synthesis step lands in ``agent_traces``."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[("Intro", "Cells everywhere. " * 8)],
    )
    await ingest_course(db_session, course.id)

    lid = (await db_session.execute(select(Lesson.id))).scalar_one()

    plan_reply = json.dumps(
        {
            "tool_calls": [
                {
                    "tool_name": "retriever",
                    "args": {"query": "cells"},
                    "rationale": "Anchor.",
                }
            ],
            "confidence_after_plan": 5,
            "final_answer_hint": None,
        }
    )
    user_id = _uid()
    _install_provider(monkeypatch, [plan_reply, f"Cells are foundational [L:{lid}]."])

    await tutor_orchestrator.orchestrate(
        db_session,
        user_id=user_id,
        course=course,
        question="cells please",
    )

    rows = (
        (await db_session.execute(select(AgentTrace).where(AgentTrace.user_id == user_id)))
        .scalars()
        .all()
    )
    steps = {r.step for r in rows}
    # At minimum: a plan step, a tool_call step, a sub_agent.retriever
    # step (recorded by the retriever sub-agent itself), and a
    # synthesis step.
    assert "plan" in steps
    assert "tool_call" in steps
    assert "sub_agent.retriever" in steps
    assert "synthesis" in steps


# ---------- ``tutor.ask`` backwards-compat ----------


async def test_ask_refusal_on_empty_retrieval_preserved(
    db_session: AsyncSession, make_user
) -> None:
    """Empty course → REFUSAL_TEXT *without* an LLM call (cost guard)."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(db_session, owner_id=owner.id, lesson_bodies=[])
    result = await tutor_service.ask(db_session, course=course, user_message="anything")
    assert result.refused is True
    assert result.answer == tutor_service.REFUSAL_TEXT


async def test_ask_blank_message_returns_refusal(db_session: AsyncSession, make_user) -> None:
    """Blank question short-circuits to refusal."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[("L", "body. " * 20)],
    )
    result = await tutor_service.ask(db_session, course=course, user_message="   ")
    assert result.refused is True


async def test_ask_with_trace_returns_orchestrator_payload(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """``ask_with_trace`` returns the OrchestratorResult alongside TutorAnswer."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[("Intro", "Cells everywhere. " * 8)],
    )
    await ingest_course(db_session, course.id)
    lid = (await db_session.execute(select(Lesson.id))).scalar_one()
    plan_reply = json.dumps(
        {
            "tool_calls": [
                {
                    "tool_name": "retriever",
                    "args": {"query": "cells"},
                    "rationale": "Anchor.",
                }
            ],
            "confidence_after_plan": 5,
            "final_answer_hint": None,
        }
    )
    _install_provider(monkeypatch, [plan_reply, f"Cells are foundational [L:{lid}]."])

    answer, orch = await tutor_service.ask_with_trace(
        db_session,
        course=course,
        user_message="What is a cell?",
        user_id=_uid(),
    )
    assert answer.refused is False
    assert lid in [c.lesson_id for c in answer.citations]
    assert len(orch.tool_calls_made) >= 1
    assert orch.confidence == 5
