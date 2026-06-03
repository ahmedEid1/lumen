"""Tutor sub-agents — per-tool unit tests (Phase I2).

One file per concept, but five sub-agents share a lot of fixture
setup, so we keep them together. Each test exercises ONE sub-agent
in isolation: it never goes through the orchestrator. The orchestrator
tests in :mod:`test_tutor_orchestrator` cover end-to-end behaviour.

Coverage per sub-agent:

* ``retriever``         — wraps :func:`find_relevant_chunks` with
  ``audit=True`` and serialises chunks + citations correctly.
* ``web_searcher``      — graceful no-op when ``TAVILY_API_KEY`` is
  absent; sane shape when the Tavily client returns results
  (mocked).
* ``code_runner``       — runs safe stdlib code, returns stdout;
  rejects banned builtins; surfaces compile + runtime errors.
* ``quiz_generator``    — happy-path JSON parses; one-shot retry on
  malformed JSON; falls back gracefully on two failures.
* ``concept_explainer`` — parses the labelled-sections reply;
  tolerates missing analogy.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    ModerationState,
    Module,
    Subject,
    Visibility,
)
from app.models.user import Role
from app.services import llm as llm_service
from app.services.embeddings_ingest import ingest_course
from app.services.tutor_subagents import (
    code_runner,
    concept_explainer,
    quiz_generator,
    retriever,
    web_searcher,
)


@pytest.fixture(autouse=True)
def _pin_providers(monkeypatch):
    """Pin embeddings + LLM to noop for every sub-agent test."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    # Ensure the web_searcher's "no key" path fires by default;
    # individual tests opt-in via monkeypatch when exercising the
    # Tavily-mocked path.
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _uid() -> str:
    return f"u-{uuid.uuid4().hex[:16]}"


async def _seed_course(
    db: AsyncSession, *, owner_id: str, lesson_bodies: list[tuple[str, str]]
) -> Course:
    """Persist a Subject + Course + Module + N text lessons."""
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subject.id,
        title=f"Test Course {suffix}",
        slug=f"test-{suffix}",
        overview="overview",
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        # S2 / ADR-0029: the retriever sub-agent ANDs the retrieval ACL keyed
        # on the requesting ``user_id`` (a random non-owner here). Only a
        # publicly listed course — public + published + moderation-approved —
        # surfaces its chunks to a non-owner.
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
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
    """Plays back canned LLM replies. Mirrors the learning-path tests."""

    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[llm_service.ChatMessage]] = []

    async def chat(self, messages, temperature: float = 0.2) -> str:  # type: ignore[no-untyped-def]
        del temperature
        self.calls.append(list(messages))
        if not self._replies:
            raise AssertionError("scripted queue exhausted")
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


# ---------- retriever ----------


async def test_retriever_returns_chunks_and_citations(db_session: AsyncSession, make_user) -> None:
    """Happy path: chunks come back; citation list is deduped lesson ids."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(
        db_session,
        owner_id=owner.id,
        lesson_bodies=[
            ("Photosynthesis", "Plants use chlorophyll to convert sunlight. " * 8),
            ("Respiration", "Cells produce ATP via cellular respiration. " * 8),
        ],
    )
    await ingest_course(db_session, course.id)

    result = await retriever.run(
        db_session,
        course=course,
        query="how do plants make food?",
        user_id=_uid(),
        top_k=4,
    )
    assert len(result.chunks) >= 1
    assert len(result.citations) >= 1
    # Citations are lesson ids only — no duplicates, in retrieval order.
    assert len(result.citations) == len(set(result.citations))
    # Note shape: "found N chunk(s) across M lesson(s)".
    assert "chunk" in result.note


async def test_retriever_returns_empty_for_unembedded_course(
    db_session: AsyncSession, make_user
) -> None:
    """Course exists but no chunks — retriever returns an empty result."""
    owner = await make_user(role=Role.instructor)
    course = await _seed_course(db_session, owner_id=owner.id, lesson_bodies=[("L", "body. " * 10)])
    # No ingest_course → no chunks.
    result = await retriever.run(
        db_session,
        course=course,
        query="anything",
        user_id=_uid(),
    )
    assert result.chunks == []
    assert result.citations == []
    assert "no relevant content" in result.note


# ---------- web_searcher ----------


async def test_web_searcher_no_key_returns_empty_with_note(
    db_session: AsyncSession,
) -> None:
    """No ``TAVILY_API_KEY`` → empty snippets + a clear note."""
    result = await web_searcher.run(
        db_session,
        query="latest AI news",
        user_id=_uid(),
    )
    assert result.snippets == []
    assert result.citations == []
    assert "disabled" in result.note.lower()


async def test_web_searcher_with_key_calls_tavily_and_shapes_snippets(
    db_session: AsyncSession, monkeypatch
) -> None:
    """With a key + a mocked client, returns up to ``max_results`` snippets."""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    async def _fake_to_thread(fn, *args, **kwargs):
        del fn, args, kwargs
        return {
            "results": [
                {
                    "title": "Result A",
                    "url": "https://example.com/a",
                    "content": "Plants convert sunlight via chlorophyll" + " filler" * 50,
                },
                {
                    "title": "Result B",
                    "url": "https://example.com/b",
                    "content": "Photosynthesis is the process",
                },
            ]
        }

    monkeypatch.setattr(
        "app.services.tutor_subagents.web_searcher.asyncio.to_thread",
        _fake_to_thread,
    )

    result = await web_searcher.run(
        db_session,
        query="how does photosynthesis work?",
        user_id=_uid(),
        max_results=5,
    )
    assert len(result.snippets) == 2
    assert result.snippets[0].title == "Result A"
    assert result.snippets[0].url == "https://example.com/a"
    # Long content gets clipped at the documented cap.
    assert len(result.snippets[0].content_first_240) <= 250
    assert result.citations == [
        "https://example.com/a",
        "https://example.com/b",
    ]


# ---------- code_runner ----------


async def test_code_runner_runs_safe_stdlib_code(
    db_session: AsyncSession,
) -> None:
    """Simple statistics call lands a clean stdout + exit_code=0."""
    code = "import statistics\nprint(statistics.mean([4, 6, 8, 10, 12]))"
    result = await code_runner.run(db_session, code=code, user_id=_uid())
    assert result.exit_code == 0
    assert "8" in result.stdout
    assert result.error_msg is None


async def test_code_runner_blocks_banned_module_import(
    db_session: AsyncSession,
) -> None:
    """``import os`` raises inside the sandbox."""
    code = "import os\nprint(os.listdir('.'))"
    result = await code_runner.run(db_session, code=code, user_id=_uid())
    assert result.exit_code != 0
    # Either compile error or runtime error mentioning ``os``.
    assert result.error_msg is not None


async def test_code_runner_handles_blank_code(
    db_session: AsyncSession,
) -> None:
    """Empty code → ``exit_code=2`` and a clear error message."""
    result = await code_runner.run(db_session, code="   ", user_id=_uid())
    assert result.exit_code == 2
    assert result.error_msg is not None


# ---------- quiz_generator ----------


async def test_quiz_generator_happy_path(db_session: AsyncSession, monkeypatch) -> None:
    """Valid JSON on first try → a populated QuizGenResult."""
    payload = json.dumps(
        {
            "prompt": "What does ATP stand for?",
            "options": [
                "Adenosine triphosphate",
                "Aluminium tetraphosphate",
                "Atmospheric trapped photons",
                "Anti-thymocyte protein",
            ],
            "answer_index": 0,
            "explanation": "ATP is adenosine triphosphate; cellular energy currency.",
        }
    )
    _install_provider(monkeypatch, [payload])

    result = await quiz_generator.run(
        db_session,
        topic="cellular respiration",
        context="ATP fuels metabolic work in every living cell.",
        user_id=_uid(),
    )
    assert result.prompt == "What does ATP stand for?"
    assert len(result.options) == 4
    assert result.answer_index == 0
    assert result.note == ""


async def test_quiz_generator_recovers_on_retry(db_session: AsyncSession, monkeypatch) -> None:
    """First reply unparsable, second valid → recovered_on_retry trace + good result."""
    valid = json.dumps(
        {
            "prompt": "What's 2+2?",
            "options": ["3", "4", "5"],
            "answer_index": 1,
            "explanation": "Simple arithmetic.",
        }
    )
    _install_provider(monkeypatch, ["not valid json at all", valid])

    result = await quiz_generator.run(
        db_session,
        topic="arithmetic",
        context="",
        user_id=_uid(),
    )
    assert result.prompt == "What's 2+2?"
    assert result.answer_index == 1


async def test_quiz_generator_falls_back_on_two_failures(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Two unparsable replies → fallback stub, NOT an exception."""
    _install_provider(monkeypatch, ["garbage 1", "garbage 2"])
    result = await quiz_generator.run(
        db_session,
        topic="anything",
        context="",
        user_id=_uid(),
    )
    assert result.prompt == "(quiz generation unavailable)"
    assert result.note  # non-empty failure reason


# ---------- concept_explainer ----------


async def test_concept_explainer_parses_labelled_sections(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Labelled-sections format parses into explanation + analogy."""
    reply = (
        "EXPLANATION:\n"
        "Photosynthesis is how plants make their own food using light.\n"
        "Sunlight + water + carbon dioxide → sugar + oxygen.\n\n"
        "ANALOGY:\n"
        "Think of a leaf as a tiny solar panel and a kitchen rolled into one."
    )
    _install_provider(monkeypatch, [reply])

    result = await concept_explainer.run(
        db_session,
        concept="photosynthesis",
        context="Plants use chlorophyll to capture sunlight.",
        user_id=_uid(),
    )
    assert "Photosynthesis is how plants" in result.explanation
    assert result.analogy is not None
    assert "solar panel" in result.analogy


async def test_concept_explainer_tolerates_missing_analogy(
    db_session: AsyncSession, monkeypatch
) -> None:
    """Empty ANALOGY section → analogy is None, explanation still set."""
    reply = "EXPLANATION:\nMitochondria generate ATP, the chemical fuel of the cell.\n\nANALOGY:\n"
    _install_provider(monkeypatch, [reply])

    result = await concept_explainer.run(
        db_session,
        concept="mitochondria",
        context="",
        user_id=_uid(),
    )
    assert "Mitochondria generate ATP" in result.explanation
    assert result.analogy is None
