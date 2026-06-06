"""S3.7 hardening — per-phase commit + honest completion marker (Codex P1).

The Codex confirm-round found two P1s in the shell-first build:

* **P1#1** — the refill UPDATEd the shell ``courses`` row (FOR NO KEY UPDATE) and
  the request transaction held that parent-row lock across the ENTIRE lesson-
  drafting loop. ``cancel_build`` + the failure-flip (separate sessions) both
  UPDATE that row, so they blocked for the whole build; the per-lesson cancel
  fence never observed the cancel. The fix: commit the outline-phase parent-row
  UPDATE (+ skeleton) in its OWN short transaction BEFORE the loop, so the loop's
  child writes take only ``FOR KEY SHARE`` on the parent and a concurrent cancel
  lands promptly. The proof here is a no-hang: a second session UPDATEs the status
  mid-loop and the fence aborts within one lesson WITHOUT blocking.

* **P1#2** — the refill unconditionally reset ``status=draft``, erasing a cancel
  that flipped the shell to ``build_failed`` between shell-materialization and the
  refill. The fix: re-read the shell FOR UPDATE and ABORT if already
  ``build_failed`` (never reset to draft).

Plus the honest completion marker: ``build_completed_at`` (migration 0052)
replaces the fragile ">=1 module" success heuristic — a crashed/cancelled mid-
build draft HAS modules but a NULL ``build_completed_at`` → re-buildable, never
replayed as success.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import AccessRevokedError
from app.db.base import get_sessionmaker
from app.models.course import Course, CourseStatus, Module, Subject, Visibility
from app.models.learning_brief import LearningBrief
from app.models.user import Role, User
from app.services import authoring_orchestrator as orch
from app.services import build as build_service
from app.services import llm as llm_service

pytestmark = pytest.mark.asyncio

# A hard ceiling so a regression that re-introduces the parent-row lock surfaces
# as a FAILED test (TimeoutError) instead of a hung CI job — the no-hang IS the
# P1#1 proof.
_NO_HANG_TIMEOUT_S = 20.0


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
    monkeypatch.setattr(orch.llm_service, "get_provider", lambda: prov)
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
        source_goal_enc=secrets_crypto.encrypt(b"learn go"),
        goal_summary="Learn Go.",
        level="beginner",
        prior_knowledge="some C",
        time_budget_hours=10,
        desired_outcomes=["Write a CLI"],
        finalized_at=datetime.now(UTC),
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return brief


# A two-module / multi-lesson outline so the loop has >=2 fence iterations.
_OUTLINE = {
    "title": "Go Basics",
    "overview": "An intro.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [
                {"title": "Install", "type": "text"},
                {"title": "Hello", "type": "text"},
            ],
        },
        {
            "title": "Core",
            "lessons": [
                {"title": "Types", "type": "text"},
                {"title": "Quiz", "type": "quiz"},
            ],
        },
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
    """Outline + critic-accept + 4 lesson bodies (3 text + 1 quiz) + final critic."""
    return [
        json.dumps(_OUTLINE),
        json.dumps(
            {"scores": {"coverage": 5, "learning_arc": 5, "scope": 5}, "weak_spots": [], "rationale": "ok"}
        ),
        _LESSON_DOC,
        _LESSON_DOC,
        _LESSON_DOC,
        _QUIZ_JSON,
        json.dumps(
            {"scores": {"coverage": 4, "learning_arc": 4, "scope": 4}, "weak_spots": [], "rationale": "ok"}
        ),
    ]


# ---------- 1. Crash mid-loop → un-built draft, re-buildable ----------


async def test_crash_mid_loop_leaves_unbuilt_rebuildable(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A crash AFTER >=1 module is committed leaves a ``draft`` with modules but a
    NULL ``build_completed_at`` — ``_is_successfully_built`` reports False and a
    re-run rebuilds (NOT replayed as success: the exact ">=1 module isn't enough"
    regression).

    Driven through the orchestrator directly (no ``build_from_brief`` failure-flip)
    to model process death — the failure handler never runs, so the course stays
    ``draft`` (not ``build_failed``).
    """
    user = await make_user(role=Role.instructor)
    user_id = user.id
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user_id)
    brief_id = brief.id
    shell_id = await build_service._materialize_build_shell(user=user, brief_id=brief_id)

    _install_provider(monkeypatch, _happy_queue())

    # Raise on the 2nd lesson — after the skeleton (all modules) is committed by
    # the outline phase and at least one lesson has been drafted.
    real = orch._draft_lesson_content
    state = {"n": 0}

    async def _boom(*args, **kwargs):
        state["n"] += 1
        if state["n"] >= 2:
            raise RuntimeError("simulated process death mid-loop")
        return await real(*args, **kwargs)

    monkeypatch.setattr(orch, "_draft_lesson_content", _boom)

    with pytest.raises(RuntimeError):
        await orch.draft_course(
            db_session, user=user, brief_id=brief_id, existing_course_id=shell_id
        )
    await db_session.rollback()  # the request session rolls back on the crash

    # A FRESH session sees the durable partial: draft, HAS modules, NULL completion.
    async with get_sessionmaker()() as fresh:
        course = await build_service.find_course_for_brief(
            fresh, owner_id=user_id, brief_id=brief_id
        )
        assert course is not None
        assert course.status == CourseStatus.draft  # NOT build_failed (no flip ran)
        assert len(course.modules) > 0  # skeleton committed by the outline phase
        assert course.build_completed_at is None  # the honest marker: un-built
        assert build_service._is_successfully_built(course) is False

    # A healthy re-run rebuilds the SAME shell (not replayed as the partial draft).
    monkeypatch.setattr(orch, "_draft_lesson_content", real)
    _install_provider(monkeypatch, _happy_queue())
    rebuild_user = await db_session.get(User, user_id)
    result = await build_service.build_from_brief(
        db_session, user=rebuild_user, brief_id=brief_id
    )
    assert result.course_id == shell_id
    rebuilt = await db_session.get(Course, shell_id)
    await db_session.refresh(rebuilt)
    assert rebuilt is not None
    assert rebuilt.status == CourseStatus.draft
    assert rebuilt.build_completed_at is not None  # now genuinely built


# ---------- 2. Cancel landing DURING the loop → fence aborts, NO HANG (P1#1) ----------


async def test_cancel_during_loop_aborts_without_hang(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A cancel (a second session's UPDATE to build_failed) that lands DURING the
    lesson loop is observed by the per-lesson fence within one lesson — and the
    second session's UPDATE does NOT block on the build's transaction.

    The no-hang is the P1#1 proof: if the request transaction still held the
    parent-row write lock across the loop, the second session's UPDATE would block
    to txn-end and this test would time out.
    """
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    shell_id = await build_service._materialize_build_shell(user=user, brief_id=brief.id)

    _install_provider(monkeypatch, _happy_queue())

    real = orch._draft_lesson_content
    state = {"n": 0, "blocked": False}

    async def _cancel_mid_loop(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            # Simulate a concurrent cancel: a SEPARATE session UPDATEs the course
            # to build_failed. This MUST NOT block on the build's open request txn
            # (it would, pre-fix, because the refill held FOR NO KEY UPDATE across
            # the loop). Guard it with wait_for so a block becomes a TimeoutError.
            async def _flip() -> None:
                async with get_sessionmaker()() as sess, sess.begin():
                    await sess.execute(
                        update(Course)
                        .where(Course.id == shell_id)
                        .values(status=CourseStatus.build_failed, visibility=Visibility.private)
                    )

            try:
                await asyncio.wait_for(_flip(), timeout=_NO_HANG_TIMEOUT_S)
            except TimeoutError as exc:  # pragma: no cover — the P1#1 regression signal
                state["blocked"] = True
                raise AssertionError(
                    "concurrent cancel UPDATE blocked on the build txn — the loop "
                    "is still holding the parent-row write lock (P1#1 regressed)"
                ) from exc
        return await real(*args, **kwargs)

    monkeypatch.setattr(orch, "_draft_lesson_content", _cancel_mid_loop)

    # The fence on the 2nd lesson observes build_failed and aborts. The whole call
    # must finish (abort) within the no-hang ceiling.
    with pytest.raises(AccessRevokedError):
        await asyncio.wait_for(
            orch.draft_course(
                db_session, user=user, brief_id=brief.id, existing_course_id=shell_id
            ),
            timeout=_NO_HANG_TIMEOUT_S,
        )
    assert state["blocked"] is False
    assert state["n"] >= 1  # at least one lesson drafted before the fence aborted


async def test_outline_phase_commits_before_loop_starts(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Structural P1#1 proof: by the time the FIRST lesson is drafted, the outline
    phase has already COMMITTED (a separate session sees the filled title +
    modules) — i.e. the loop region holds no open parent-row write transaction."""
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    shell_id = await build_service._materialize_build_shell(user=user, brief_id=brief.id)

    _install_provider(monkeypatch, _happy_queue())

    real = orch._draft_lesson_content
    observed: dict[str, object] = {}

    async def _observe(*args, **kwargs):
        if "title" not in observed:
            # A SEPARATE session reads the parent row mid-loop. It must see the
            # outline-phase commit (real title + modules), proving phase 1 already
            # committed before the loop (no open parent-row write txn).
            async with get_sessionmaker()() as sess:
                row = (
                    await sess.execute(select(Course).where(Course.id == shell_id))
                ).scalar_one()
                mods = (
                    (await sess.execute(select(Module).where(Module.course_id == shell_id)))
                    .scalars()
                    .all()
                )
                observed["title"] = row.title
                observed["modules"] = len(mods)
                observed["build_completed_at"] = row.build_completed_at
        return await real(*args, **kwargs)

    monkeypatch.setattr(orch, "_draft_lesson_content", _observe)
    await orch.draft_course(
        db_session, user=user, brief_id=brief.id, existing_course_id=shell_id
    )

    assert observed["title"] == _OUTLINE["title"]  # outline UPDATE was committed
    assert observed["modules"] == len(_OUTLINE["modules"])  # skeleton committed
    # build_completed_at is NOT stamped yet during the loop — only at the very end.
    assert observed["build_completed_at"] is None


# ---------- 3. Refill on an already-build_failed shell aborts, no reset (P1#2) ----------


async def test_refill_on_build_failed_shell_aborts_no_reset(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A cancel that flips the shell to ``build_failed`` between materialization and
    the refill makes the refill ABORT (define.build_cancelled) — it must NOT reset
    the shell back to ``draft`` (P1#2)."""
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    shell_id = await build_service._materialize_build_shell(user=user, brief_id=brief.id)

    # The owner cancelled before the refill landed → shell is build_failed.
    async with get_sessionmaker()() as sess, sess.begin():
        await sess.execute(
            update(Course)
            .where(Course.id == shell_id)
            .values(status=CourseStatus.build_failed, visibility=Visibility.private)
        )

    _install_provider(monkeypatch, _happy_queue())

    # The refill re-reads FOR UPDATE, sees build_failed, and aborts.
    from app.services import ai_authoring

    outline = ai_authoring.CourseOutline.model_validate(_OUTLINE)
    bb = orch._BuildBrief(
        brief_id=brief.id,
        goal_text="learn go",
        goal_summary="Learn Go.",
        difficulty=orch.Difficulty.beginner,
        level="beginner",
        time_budget_hours=10,
        target_modules=2,
        desired_outcomes=["Write a CLI"],
        desired_subject_hint=None,
    )
    subject = await _personal_subject(db_session)
    with pytest.raises(AccessRevokedError) as exc:
        await orch._persist_outline_shell(
            db_session,
            user=user,
            subject_id=subject.id,
            outline=outline,
            build_brief=bb,
            existing_course_id=shell_id,
        )
    assert exc.value.code == "define.build_cancelled"

    # The shell stays build_failed — NOT reset to draft.
    async with get_sessionmaker()() as fresh:
        row = (await fresh.execute(select(Course).where(Course.id == shell_id))).scalar_one()
        assert row.status == CourseStatus.build_failed
        assert row.build_completed_at is None


async def test_cancel_before_refill_through_build_from_brief_stays_failed(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """End-to-end P1#2: a cancel that lands between shell-materialization and the
    refill drives ``build_from_brief`` to ``DefineBuildFailedError`` and leaves the
    course ``build_failed`` (NEVER reset to draft, never replayed as success)."""
    from app.core.errors import DefineBuildFailedError

    user = await make_user(role=Role.instructor)
    user_id = user.id
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user_id)
    brief_id = brief.id

    _install_provider(monkeypatch, _happy_queue())

    # Wrap the real shell materializer to simulate an owner cancel that lands in the
    # window between materialization and the refill (flip to build_failed).
    real_materialize = build_service._materialize_build_shell

    async def _materialize_then_cancel(*, user, brief_id):
        shell_id = await real_materialize(user=user, brief_id=brief_id)
        async with get_sessionmaker()() as sess, sess.begin():
            await sess.execute(
                update(Course)
                .where(Course.id == shell_id)
                .values(status=CourseStatus.build_failed, visibility=Visibility.private)
            )
        return shell_id

    monkeypatch.setattr(build_service, "_materialize_build_shell", _materialize_then_cancel)

    with pytest.raises(DefineBuildFailedError):
        await build_service.build_from_brief(db_session, user=user, brief_id=brief_id)

    async with get_sessionmaker()() as fresh:
        course = await build_service.find_course_for_brief(
            fresh, owner_id=user_id, brief_id=brief_id
        )
        assert course is not None
        assert course.status == CourseStatus.build_failed  # NOT reset to draft
        assert course.build_completed_at is None
        assert build_service._is_successfully_built(course) is False


# ---------- 4. Successful build stamps the marker + replays ----------


async def test_successful_build_stamps_completed_and_replays(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A successful build stamps ``build_completed_at`` (so ``_is_successfully_built``
    is True) and the replay short-circuit returns it WITHOUT a second LLM run."""
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)

    _install_provider(monkeypatch, _happy_queue())
    first = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)

    built = await db_session.get(Course, first.course_id)
    await db_session.refresh(built)
    assert built is not None
    assert built.status == CourseStatus.draft
    assert built.build_completed_at is not None

    course = await build_service.find_course_for_brief(
        db_session, owner_id=user.id, brief_id=brief.id
    )
    assert course is not None
    assert build_service._is_successfully_built(course) is True

    # Replay: a second submit returns the same course with NO second LLM call.
    prov2 = _install_provider(monkeypatch, [])  # would raise if any call lands
    second = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    assert second.course_id == first.course_id
    assert prov2.calls == []
