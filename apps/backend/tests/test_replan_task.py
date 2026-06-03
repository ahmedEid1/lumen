"""Monthly learning-path re-planner Celery task (Phase I5).

Exercises the async core (``replan_paths_monthly_async``) directly,
skipping the Celery transport so we don't need a broker in tests.
Assertions:

* Stale paths get re-planned; fresh ones do not.
* Per-user errors are swallowed; one failure doesn't block the
  rest of the cohort.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import (
    Course,
    CourseStatus,
    Difficulty,
    Lesson,
    LessonType,
    Module,
    Subject,
)
from app.models.learning_path import (
    PATH_STATUS_ACTIVE,
    PATH_STATUS_ARCHIVED,
    LearningPath,
)
from app.models.user import Role
from app.services import learning_path as learning_path_service
from app.services import llm as llm_service
from app.services.embeddings_ingest import ingest_course
from app.workers.tasks import learning_path as replan_task

# ---------- Scripted provider (mirrors service/api tests) ----------


class _ScriptedProvider:
    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)

    async def chat(self, messages, temperature: float = 0.2) -> str:
        del temperature
        if not self._replies:
            raise AssertionError("ScriptedProvider queue exhausted")
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
def _settings_overrides(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def _seed_catalog(db: AsyncSession, *, owner_id: str, n: int = 3) -> list[str]:
    slugs: list[str] = []
    for i in range(n):
        suffix = uuid.uuid4().hex[:6]
        subject = Subject(title=f"S {suffix}", slug=f"subj-{suffix}")
        db.add(subject)
        await db.flush()
        course = Course(
            owner_id=owner_id,
            subject_id=subject.id,
            title=f"Course {i}",
            slug=f"rep-c{i}-{suffix}",
            overview=f"o {i}",
            difficulty=Difficulty.beginner,
            status=CourseStatus.published,
        )
        db.add(course)
        await db.flush()
        module = Module(course_id=course.id, title="M", order=0)
        db.add(module)
        await db.flush()
        db.add(
            Lesson(
                module_id=module.id,
                title=f"L {i}",
                order=0,
                type=LessonType.text,
                data={"type": "text", "body_markdown": f"body {i}"},
            )
        )
        await db.commit()
        await ingest_course(db, course.id)
        slugs.append(course.slug)
    return slugs


def _valid_plan(slugs: list[str]) -> str:
    third = max(1, len(slugs) // 3)
    return json.dumps(
        {
            "milestones": [
                {"name": "M1", "weeks": "1-4", "course_slugs": slugs[:third]},
                {
                    "name": "M2",
                    "weeks": "5-12",
                    "course_slugs": slugs[third : third * 2] or [slugs[-1]],
                },
                {
                    "name": "M3",
                    "weeks": "13+",
                    "course_slugs": slugs[third * 2 :] or [slugs[-1]],
                },
            ],
            "rationale": "ok",
        }
    )


# ---------- Tests ----------


async def test_replan_skips_fresh_paths(db_session: AsyncSession, make_user, monkeypatch) -> None:
    """A path with replanned_at within the staleness window is skipped."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)

    # Build a path via the service (so the row is well-formed),
    # then make sure replanned_at is recent (it is by default).
    prov = _ScriptedProvider([_valid_plan(slugs)])
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    path = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    await db_session.commit()
    assert path.replanned_at > datetime.now(UTC) - timedelta(minutes=5)

    # Run the task — there should be no stale candidates, so it's
    # a no-op and the LLM is never called.
    monkeypatch.setattr(
        llm_service,
        "get_provider",
        lambda: _ScriptedProvider([]),  # would raise on use
    )
    succeeded = await replan_task.replan_paths_monthly_async()
    assert succeeded == 0
    # The original path is still active and unchanged.
    refreshed = await db_session.get(LearningPath, path.id)
    assert refreshed is not None
    assert refreshed.status == PATH_STATUS_ACTIVE


async def test_replan_picks_up_stale_paths(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A path older than 30 days gets re-planned."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)

    prov = _ScriptedProvider([_valid_plan(slugs), _valid_plan(slugs)])
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)

    initial = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    # Backdate ``replanned_at`` so the beat job picks it up.
    initial.replanned_at = datetime.now(UTC) - timedelta(days=45)
    await db_session.commit()

    succeeded = await replan_task.replan_paths_monthly_async()
    assert succeeded == 1

    # The beat job commits in a *separate* session, so ``db_session``'s
    # identity map still holds the cached ``initial`` row with its
    # original ``status='active'`` attribute (the conftest configures
    # ``expire_on_commit=False`` so committed objects keep their loaded
    # state — see ``conftest._engine``). Without expiring, the SELECT
    # below returns the cached object and the test sees a stale
    # ``status``. ``expunge_all`` removes the cached objects from the
    # session entirely so the next query returns fresh instances
    # whose attributes match the DB. ``expire_all`` marks them
    # expired-but-still-in-the-identity-map, which means attribute
    # access triggers a lazy reload — and lazy reloads in async
    # SQLAlchemy require a greenlet context the bare list-comp below
    # doesn't provide (MissingGreenlet). ``expunge_all`` sidesteps
    # the whole expired-attribute path. Synchronous on AsyncSession.
    db_session.expunge_all()

    # The original path is archived, a fresh active one exists.
    rows = (
        (await db_session.execute(select(LearningPath).where(LearningPath.user_id == learner.id)))
        .scalars()
        .all()
    )
    active = [p for p in rows if p.status == PATH_STATUS_ACTIVE]
    archived = [p for p in rows if p.status == PATH_STATUS_ARCHIVED]
    assert len(active) == 1
    assert len(archived) == 1
    assert active[0].id != initial.id


async def test_replan_swallows_per_user_errors(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """One learner's failure doesn't stop the rest of the cohort."""
    teacher = await make_user(role=Role.instructor)
    good = await make_user(role=Role.student)
    bad = await make_user(role=Role.student)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)

    # Both build paths with the scripted provider.
    prov = _ScriptedProvider([_valid_plan(slugs), _valid_plan(slugs)])
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    p_good = await learning_path_service.build_path(db_session, user_id=good.id, goal="A")
    p_bad = await learning_path_service.build_path(db_session, user_id=bad.id, goal="B")
    p_good.replanned_at = datetime.now(UTC) - timedelta(days=45)
    p_bad.replanned_at = datetime.now(UTC) - timedelta(days=45)
    await db_session.commit()

    # Now: the next two replan calls — one per user — get a
    # failing provider for the BAD user and a valid one for the GOOD
    # user. We can't easily control which gets called first since
    # the task picks by SQL order, so we make the provider raise
    # only for one specific learner by patching ``replan_for_user``
    # to fail for ``bad`` and succeed for ``good``.
    real_replan = learning_path_service.replan_for_user

    async def _selective(db, *, user_id, ctx=None):
        if user_id == bad.id:
            raise RuntimeError("simulated failure for the bad learner")
        # S5: forward the initiation ctx (PLATFORM_CONTEXT from the beat);
        # fall back to the service default when a caller omits it.
        if ctx is None:
            return await real_replan(db, user_id=user_id)
        return await real_replan(db, user_id=user_id, ctx=ctx)

    monkeypatch.setattr(learning_path_service, "replan_for_user", _selective)
    # Also patch the bound name inside the task module — Python
    # binds the reference at import time.
    monkeypatch.setattr(
        replan_task.learning_path_service,
        "replan_for_user",
        _selective,
    )
    # Good user still goes through the real path, which needs a
    # valid scripted reply.
    monkeypatch.setattr(
        llm_service,
        "get_provider",
        lambda: _ScriptedProvider([_valid_plan(slugs)]),
    )

    succeeded = await replan_task.replan_paths_monthly_async()
    # Exactly one succeeded — the good learner. The bad learner's
    # exception was swallowed.
    assert succeeded == 1


async def test_replan_handles_empty_cohort(monkeypatch) -> None:
    """No learners at all → returns 0 without raising."""
    succeeded = await replan_task.replan_paths_monthly_async()
    assert succeeded == 0
