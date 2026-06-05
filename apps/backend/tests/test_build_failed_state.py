"""S3.7 — ``build_failed`` course state + re-runnable build (FR-DEFINE-15).

A self-serve build that fails unrecoverably never leaves a silent half-course: it
leaves a ``status=build_failed`` shell (excluded from catalog/search/research),
surfaces a NORMALIZED error (no raw model/vendor output), and is re-runnable —
re-submitting the same finalized brief flips the course back to a clean ``draft``.

Driven through the ``services.build.build_from_brief`` seam against the scripted
LLM provider (an outliner double-failure is the canonical unrecoverable failure).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import DefineBuildFailedError
from app.models.course import Course, CourseStatus, Subject, Visibility
from app.models.learning_brief import LearningBrief
from app.models.user import Role
from app.services import build as build_service
from app.services import llm as llm_service
from app.services import visibility as visibility_service

pytestmark = pytest.mark.asyncio


class _ScriptedProvider:
    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list] = []

    async def chat(self, messages, temperature: float = 0.2) -> str:
        self.calls.append(list(messages))
        if not self._replies:
            raise AssertionError("ScriptedProvider queue exhausted.")
        return self._replies.pop(0)

    async def chat_with_usage(self, messages, temperature: float = 0.2):
        text = await self.chat(messages, temperature=temperature)
        return llm_service.ChatResponse(
            text=text, prompt_tokens=16, completion_tokens=16, model=self._model
        )


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


async def _personal_subject(db: AsyncSession) -> Subject:
    slug = get_settings().personal_subject_slug
    from app.repositories import courses as courses_repo

    existing = await courses_repo.get_subject_by_slug(db, slug)
    if existing is not None:
        return existing
    subj = Subject(title="Personal", slug=slug)
    db.add(subj)
    await db.commit()
    await db.refresh(subj)
    return subj


async def _finalized_brief(db: AsyncSession, *, owner_id: str) -> LearningBrief:
    brief = LearningBrief(
        owner_id=owner_id,
        source_goal_enc=secrets_crypto.encrypt(b"learn rust"),
        goal_summary="Learn Rust.",
        level="beginner",
        prior_knowledge="some C",
        time_budget_hours=10,
        desired_outcomes=["Write safe Rust"],
        finalized_at=datetime.now(UTC),
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


import json

_OUTLINE = {
    "title": "Rust Basics",
    "overview": "An intro.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [
                {"title": "Install", "type": "text"},
                {"title": "Quiz", "type": "quiz"},
            ],
        }
    ],
}
_LESSON_DOC = json.dumps(
    {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "B."}]}]}
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


def _happy_queue() -> list[str]:
    return [
        json.dumps(_OUTLINE),
        json.dumps(
            {
                "scores": {"coverage": 5, "learning_arc": 5, "scope": 5},
                "weak_spots": [],
                "rationale": "ok",
            }
        ),
        _LESSON_DOC,
        _QUIZ_JSON,
        json.dumps(
            {
                "scores": {"coverage": 4, "learning_arc": 4, "scope": 4},
                "weak_spots": [],
                "rationale": "ok",
            }
        ),
    ]


# ---------- build_failed materialization ----------


async def test_outliner_failure_leaves_build_failed_course(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    # Two unparseable outliner replies → the orchestrator raises outliner_failed.
    _install_provider(monkeypatch, ["not json", "still not json"])

    with pytest.raises(DefineBuildFailedError) as exc:
        await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    # Normalized, user-safe error — no raw model output ("not json") leaks.
    assert "not json" not in exc.value.message
    assert exc.value.code == "define.build_failed"

    # A build_failed shell exists for this brief.
    course = await build_service.find_course_for_brief(
        db_session, owner_id=user.id, brief_id=brief.id
    )
    assert course is not None
    assert course.status == CourseStatus.build_failed
    assert course.visibility == Visibility.private


async def test_build_failed_excluded_from_owner_retrieval(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A build_failed course is excluded from the owner's cross-course RAG ACL
    (R-S12) — the retrieval_acl_clause string literal must match the enum value."""
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    _install_provider(monkeypatch, ["not json", "still not json"])
    with pytest.raises(DefineBuildFailedError):
        await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)

    course = await build_service.find_course_for_brief(
        db_session, owner_id=user.id, brief_id=brief.id
    )
    assert course is not None
    clause = visibility_service.retrieval_acl_clause(user.id)
    rows = (
        (await db_session.execute(select(Course.id).where(Course.id == course.id, clause)))
        .scalars()
        .all()
    )
    assert rows == []  # the owner's own failed draft does NOT leak into their RAG


async def test_rerun_flips_build_failed_to_draft(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)

    _install_provider(monkeypatch, ["not json", "still not json"])
    with pytest.raises(DefineBuildFailedError):
        await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    failed = await build_service.find_course_for_brief(
        db_session, owner_id=user.id, brief_id=brief.id
    )
    assert failed is not None and failed.status == CourseStatus.build_failed

    # Re-run with a healthy provider → the build succeeds and the course is a
    # clean draft again (re-runnable, no manual deletion).
    _install_provider(monkeypatch, _happy_queue())
    result = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    rebuilt = await db_session.get(Course, result.course_id)
    assert rebuilt is not None
    assert rebuilt.status == CourseStatus.draft
    assert rebuilt.visibility == Visibility.private


async def test_rerun_reuses_same_shell_no_duplicate_course(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A re-run of a failed brief reuses the SAME course row (one course, not two).

    Shell-first (S3.7): the failed shell IS the row the success path fills, so a
    re-run flips it back to ``draft`` in place rather than minting a second course.
    """
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)

    _install_provider(monkeypatch, ["not json", "still not json"])
    with pytest.raises(DefineBuildFailedError):
        await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    failed = await build_service.find_course_for_brief(
        db_session, owner_id=user.id, brief_id=brief.id
    )
    assert failed is not None

    _install_provider(monkeypatch, _happy_queue())
    result = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    assert result.course_id == failed.id  # same row reused, not a duplicate

    all_courses = (
        (await db_session.execute(select(Course.id).where(Course.owner_id == user.id)))
        .scalars()
        .all()
    )
    assert len(all_courses) == 1


# ---------- Shell-first durability: the exact Codex P1 repro ----------


async def test_shell_survives_request_session_rollback(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """The build_failed shell PERSISTS even when the REQUEST session rolls back.

    The Codex P1 bug: the old design materialized the build_failed shell inside the
    request session; ``get_db`` rolls the whole session back on the raised
    exception, so NO row survived on the outliner/lesson failure path — killing
    retry/idempotency/sweep on exactly their target path. Shell-first commits the
    shell in its OWN session, so it is rollback-immune. Here we drive the build
    through a request-style session that ROLLS BACK on the exception (mimicking
    ``get_db``), then assert the shell row exists post-rollback with
    ``status=build_failed`` — read back in a SEPARATE session to prove it committed.
    """
    from app.db.base import get_sessionmaker

    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    _install_provider(monkeypatch, ["not json", "still not json"])

    sessionmaker = get_sessionmaker()
    # Mimic the get_db request lifecycle: yield a session, rollback on exception.
    req_db = sessionmaker()
    try:
        with pytest.raises(DefineBuildFailedError):
            try:
                await build_service.build_from_brief(req_db, user=user, brief_id=brief.id)
                await req_db.commit()
            except Exception:
                await req_db.rollback()  # exactly what get_db does
                raise
    finally:
        await req_db.close()

    # A FRESH session sees the committed shell, build_failed, despite the rollback.
    async with sessionmaker() as fresh:
        course = await build_service.find_course_for_brief(
            fresh, owner_id=user.id, brief_id=brief.id
        )
        assert course is not None, "shell must survive the request rollback (Codex P1)"
        assert course.status == CourseStatus.build_failed
        assert course.visibility == Visibility.private


async def test_empty_shell_not_replayed_as_success(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """An empty (mid-build/crashed) ``draft`` shell is re-buildable, never replayed.

    Invariant 2: shell-first commits an EMPTY ``draft`` before the pipeline runs.
    A crash that never reaches the failure handler leaves a module-less ``draft``.
    The replay short-circuit must NOT return that empty shell as a successful build
    — it must fall through to a real re-run. We simulate the crash by committing a
    bare shell (no modules), then a healthy re-run must produce a FILLED course.
    """
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)

    # Simulate a crashed build: an empty draft shell, committed, with the brief link.
    shell_id = await build_service._materialize_build_shell(user=user, brief_id=brief.id)
    shell = await build_service.find_course_for_brief(
        db_session, owner_id=user.id, brief_id=brief.id
    )
    assert shell is not None
    assert shell.id == shell_id
    assert shell.status == CourseStatus.draft
    assert build_service._is_successfully_built(shell) is False  # empty → not success

    # A healthy re-run fills the SAME shell — not replayed-as-empty.
    _install_provider(monkeypatch, _happy_queue())
    result = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    assert result.course_id == shell_id
    assert result.module_count >= 1  # the shell was actually filled, not replayed empty
