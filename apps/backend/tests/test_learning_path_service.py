"""Learning-path agent service tests (Phase I5).

Exercises the service layer end-to-end against a scripted LLM
provider that returns canned JSON. The catalog is real (seeded
in the test DB, chunks ingested); the LLM is the only mocked seam.

Coverage:

* ``_condense_catalog`` returns the published catalog ranked by
  chunk similarity to the goal (with the noop embedding provider).
* ``build_path`` produces a valid path, persists it + its steps,
  archives any prior active path, and tolerates a slug that the
  LLM emits but no longer exists in the catalog.
* ``mark_step_complete`` flips a step's status and is owner-scoped.
* The retry path: a malformed first reply is followed by a valid
  second reply and the build succeeds.
* The validation failure path: two malformed replies raise the
  clean ``learning_path.llm_invalid_output`` error.
* ``replan_for_user`` archives the old path and reuses the goal.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
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
from app.models.learning_path import (
    PATH_STATUS_ACTIVE,
    PATH_STATUS_ARCHIVED,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_PENDING,
    LearningPath,
)
from app.models.user import Role
from app.services import learning_path as learning_path_service
from app.services import llm as llm_service
from app.services.embeddings_ingest import ingest_course

# ---------- LLM scripting ----------


class _ScriptedProvider:
    """Plays back a canned queue of JSON replies for ``chat_with_usage``.

    Mirrors the pattern from ``test_ai_authoring.py`` but also
    surfaces the ``ChatResponse`` shape ``call_logged`` expects, so
    the path-builder's metered call path works without monkey-
    patching the cost meter.
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
def _noop_embeddings(monkeypatch):
    """Pin embeddings + LLM to noop so retrieval is deterministic."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    # H1 cost tracking — leave on so call_logged exercises the
    # metered path; budget cap is generous enough for the test calls.
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _install_provider(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    return prov


# ---------- Catalog seeding helpers ----------


async def _seed_published_course(
    db: AsyncSession,
    *,
    owner_id: str,
    title: str,
    slug: str,
    overview: str,
    lesson_bodies: list[str],
) -> Course:
    """One subject + course + module + N text lessons."""
    suffix = uuid.uuid4().hex[:6]
    subject = Subject(title=f"Subject {suffix}", slug=f"subj-{suffix}")
    db.add(subject)
    await db.flush()
    course = Course(
        owner_id=owner_id,
        subject_id=subject.id,
        title=title,
        slug=slug,
        overview=overview,
        difficulty=Difficulty.beginner,
        status=CourseStatus.published,
        # S2 / ADR-0026: a course is only publicly listed (catalog,
        # condense, retrieval ACL) when it is public + published +
        # moderation-approved. ``_condense_catalog`` and the retrieval
        # ACL now route through ``is_publicly_listed``; seed the two
        # net-new axes so these helpers see the course.
        visibility=Visibility.public,
        moderation_state=ModerationState.approved,
    )
    db.add(course)
    await db.flush()
    module = Module(course_id=course.id, title="Module 1", order=0)
    db.add(module)
    await db.flush()
    for i, body in enumerate(lesson_bodies):
        db.add(
            Lesson(
                module_id=module.id,
                title=f"Lesson {i + 1}",
                order=i,
                type=LessonType.text,
                data={"type": "text", "body_markdown": body},
            )
        )
    await db.commit()
    await db.refresh(course)
    return course


def _valid_plan_json(
    *,
    slugs: list[str],
    rationale: str = "Sequenced from foundations to depth based on your goal and current mastery.",
    next_action_slug: str | None = None,
    next_action_kind: str = "start_lesson",
) -> str:
    """Produce a plan JSON string. ``slugs`` must list 3-9 course slugs.

    We bucket them into 3 milestones of roughly equal size; the
    helper exists so each test can paramterise the slug set without
    duplicating JSON noise.
    """
    if len(slugs) < 3:
        raise ValueError("need at least 3 slugs for a 3-milestone plan")
    third = max(1, len(slugs) // 3)
    milestones = [
        {"name": "Foundations", "weeks": "1-4", "course_slugs": slugs[:third]},
        {
            "name": "Core",
            "weeks": "5-12",
            "course_slugs": slugs[third : third * 2] or [slugs[-1]],
        },
        {
            "name": "Production",
            "weeks": "13+",
            "course_slugs": slugs[third * 2 :] or [slugs[-1]],
        },
    ]
    payload: dict = {
        "milestones": milestones,
        "rationale": rationale,
    }
    if next_action_slug is not None:
        payload["next_action"] = {
            "course_slug": next_action_slug,
            "kind": next_action_kind,
        }
    return json.dumps(payload)


# ---------- _condense_catalog ----------


async def test_condense_catalog_returns_published_courses(
    db_session: AsyncSession, make_user
) -> None:
    """Top-K candidates come back as ``CourseDigest`` rows."""
    teacher = await make_user(role=Role.instructor)
    course_a = await _seed_published_course(
        db_session,
        owner_id=teacher.id,
        title="Python Basics",
        slug=f"python-basics-{uuid.uuid4().hex[:6]}",
        overview="Intro to Python for beginners — syntax, control flow.",
        lesson_bodies=[
            "Python is a high-level programming language for beginners.",
            "Functions and modules organise reusable code.",
        ],
    )
    course_b = await _seed_published_course(
        db_session,
        owner_id=teacher.id,
        title="FastAPI Intro",
        slug=f"fastapi-intro-{uuid.uuid4().hex[:6]}",
        overview="Build APIs with FastAPI: routing, validation, async.",
        lesson_bodies=[
            "FastAPI is a Python web framework with type hints.",
            "Async endpoints scale concurrent requests well.",
        ],
    )
    await ingest_course(db_session, course_a.id)
    await ingest_course(db_session, course_b.id)

    digests = await learning_path_service._condense_catalog(
        db_session, "I want to build APIs in Python", top_k=10
    )
    slugs = {d.slug for d in digests}
    assert course_a.slug in slugs
    assert course_b.slug in slugs
    for d in digests:
        assert d.title
        assert d.difficulty


async def test_condense_catalog_falls_back_when_no_chunks(
    db_session: AsyncSession, make_user
) -> None:
    """A catalog whose lessons haven't been embedded still yields candidates."""
    teacher = await make_user(role=Role.instructor)
    course = await _seed_published_course(
        db_session,
        owner_id=teacher.id,
        title="No Chunks Yet",
        slug=f"no-chunks-{uuid.uuid4().hex[:6]}",
        overview="course without embeddings",
        lesson_bodies=["text"],
    )
    # No ingest_course → no chunks in DB.
    digests = await learning_path_service._condense_catalog(db_session, "build something", top_k=5)
    slugs = {d.slug for d in digests}
    assert course.slug in slugs


# ---------- build_path ----------


async def test_build_path_persists_path_and_steps(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Happy path: valid LLM JSON → one path + 3-N steps persisted."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = []
    for i in range(4):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"course-{i}-{uuid.uuid4().hex[:6]}",
            overview=f"Overview of course {i}",
            lesson_bodies=[f"body for course {i}"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    _install_provider(
        monkeypatch,
        [
            _valid_plan_json(
                slugs=slugs,
                next_action_slug=slugs[0],
                next_action_kind="start_lesson",
            )
        ],
    )

    path = await learning_path_service.build_path(
        db_session, user_id=learner.id, goal="Become a backend engineer"
    )
    assert path.status == PATH_STATUS_ACTIVE
    assert path.goal == "Become a backend engineer"
    assert path.rationale
    assert len(path.steps) == len(slugs)
    # Positions are dense and ascending from 0.
    positions = [s.position for s in sorted(path.steps, key=lambda s: s.position)]
    assert positions == list(range(len(slugs)))
    # All steps start pending.
    assert all(s.status == STEP_STATUS_PENDING for s in path.steps)
    # next_action persisted onto the row.
    assert path.next_action is not None
    assert path.next_action["course_slug"] == slugs[0]
    assert path.next_action["kind"] == "start_lesson"


async def test_build_path_archives_previous_active(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A second ``build_path`` call archives the first path."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"c{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    _install_provider(
        monkeypatch,
        [
            _valid_plan_json(slugs=slugs, next_action_slug=slugs[0]),
            _valid_plan_json(slugs=slugs, next_action_slug=slugs[1]),
        ],
    )

    first = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal one")
    second = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal two")
    assert first.id != second.id
    # Re-read the first path; should be archived.
    refreshed = await db_session.get(LearningPath, first.id)
    assert refreshed is not None
    assert refreshed.status == PATH_STATUS_ARCHIVED
    assert second.status == PATH_STATUS_ACTIVE


async def test_build_path_drops_unresolved_slug(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A slug that's in the candidate list but disappears mid-flight is dropped.

    The validator allows it through (the candidate set contained
    it) but ``_resolve_slugs`` won't find a live course — we just
    skip that step and persist the rest.
    """
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    surviving_slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"survive-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        surviving_slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    # Patch ``_condense_catalog`` to inject a slug the catalog will
    # later reject — simulates "course soft-deleted between catalog
    # snapshot and step persistence".
    from app.services.learning_path import CourseDigest

    original = learning_path_service._condense_catalog

    async def _augmented(db, goal, *, top_k=20, embedding_provider=None, requesting_user_id=None):
        # S2 / ADR-0029: ``_condense_catalog`` now takes ``requesting_user_id``
        # so the retrieval ACL can include the caller's own live courses.
        # Mirror the real signature and forward it through.
        real = await original(db, goal, top_k=top_k, requesting_user_id=requesting_user_id)
        return [
            *real,
            CourseDigest(
                course_id="ghost-id",
                slug="ghost-slug",
                title="Ghost",
                difficulty="beginner",
                overview="not in db",
                chunk_hits=0,
            ),
        ]

    monkeypatch.setattr(learning_path_service, "_condense_catalog", _augmented)

    slugs_for_prompt = [*surviving_slugs, "ghost-slug"]
    _install_provider(
        monkeypatch,
        [_valid_plan_json(slugs=slugs_for_prompt, next_action_slug=surviving_slugs[0])],
    )

    path = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    persisted_slugs = {s.course_slug for s in path.steps}
    assert "ghost-slug" not in persisted_slugs
    assert all(s in set(surviving_slugs) for s in persisted_slugs)


async def test_build_path_recovers_on_retry(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """First reply malformed → retry succeeds → path is persisted."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"retry-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    prov = _install_provider(
        monkeypatch,
        [
            "{not valid json",  # malformed first turn
            _valid_plan_json(slugs=slugs, next_action_slug=slugs[0]),
        ],
    )
    path = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    assert len(prov.calls) == 2  # one initial + one retry
    assert path.status == PATH_STATUS_ACTIVE
    assert len(path.steps) == len(slugs)


async def test_build_path_raises_on_double_failure(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Two malformed replies raise the clean LLM-invalid-output error."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"fail-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        await ingest_course(db_session, c.id)
    _install_provider(monkeypatch, ["totally broken", "still broken"])
    with pytest.raises(AppError) as excinfo:
        await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    assert excinfo.value.code == "learning_path.llm_invalid_output"


async def test_build_path_rejects_invented_slug(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """An LLM that emits a slug NOT in the candidate list gets the retry +
    a clean rejection if it doesn't fix itself."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"real-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        await ingest_course(db_session, c.id)

    invented_plan = json.dumps(
        {
            "milestones": [
                {
                    "name": "M1",
                    "weeks": "1-4",
                    "course_slugs": ["completely-invented-course"],
                },
                {
                    "name": "M2",
                    "weeks": "5-12",
                    "course_slugs": ["also-invented"],
                },
                {
                    "name": "M3",
                    "weeks": "13+",
                    "course_slugs": ["still-invented"],
                },
            ],
            "rationale": "made-up slugs everywhere",
        }
    )
    _install_provider(monkeypatch, [invented_plan, invented_plan])
    with pytest.raises(AppError) as excinfo:
        await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    assert excinfo.value.code == "learning_path.llm_invalid_output"


# ---------- mark_step_complete ----------


async def test_mark_step_complete_flips_status(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """``mark_step_complete`` sets the step to completed for the owner."""
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"step-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    _install_provider(
        monkeypatch,
        [_valid_plan_json(slugs=slugs, next_action_slug=slugs[0])],
    )
    path = await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    step = path.steps[0]
    flipped = await learning_path_service.mark_step_complete(
        db_session, step_id=step.id, user_id=learner.id
    )
    assert flipped.status == STEP_STATUS_COMPLETED


async def test_mark_step_complete_blocks_other_users(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A step not belonging to ``user_id`` returns 404-shaped error."""
    from app.core.errors import NotFoundError

    teacher = await make_user(role=Role.instructor)
    owner = await make_user(role=Role.student)
    intruder = await make_user(role=Role.student)
    slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"intrude-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    _install_provider(
        monkeypatch,
        [_valid_plan_json(slugs=slugs, next_action_slug=slugs[0])],
    )
    path = await learning_path_service.build_path(db_session, user_id=owner.id, goal="goal")
    step = path.steps[0]
    with pytest.raises(NotFoundError):
        await learning_path_service.mark_step_complete(
            db_session, step_id=step.id, user_id=intruder.id
        )


# ---------- replan_for_user ----------


async def test_replan_for_user_archives_old_and_reuses_goal(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"replan-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)

    _install_provider(
        monkeypatch,
        [
            _valid_plan_json(slugs=slugs, next_action_slug=slugs[0]),
            _valid_plan_json(slugs=slugs, next_action_slug=slugs[1]),
        ],
    )
    first = await learning_path_service.build_path(
        db_session, user_id=learner.id, goal="be a great engineer"
    )
    second = await learning_path_service.replan_for_user(db_session, user_id=learner.id)
    assert second is not None
    assert second.id != first.id
    assert second.goal == first.goal == "be a great engineer"
    rows = (
        (await db_session.execute(select(LearningPath).where(LearningPath.user_id == learner.id)))
        .scalars()
        .all()
    )
    active = [p for p in rows if p.status == PATH_STATUS_ACTIVE]
    archived = [p for p in rows if p.status == PATH_STATUS_ARCHIVED]
    assert len(active) == 1
    assert len(archived) == 1


async def test_replan_for_user_returns_none_when_no_active(
    db_session: AsyncSession, make_user
) -> None:
    learner = await make_user(role=Role.student)
    result = await learning_path_service.replan_for_user(db_session, user_id=learner.id)
    assert result is None


# ---------- get_today_action ----------


async def test_get_today_action_returns_none_without_path(
    db_session: AsyncSession, make_user
) -> None:
    learner = await make_user(role=Role.student)
    out = await learning_path_service.get_today_action(db_session, user_id=learner.id)
    assert out is None


async def test_get_today_action_includes_due_count(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    teacher = await make_user(role=Role.instructor)
    learner = await make_user(role=Role.student)
    slugs = []
    for i in range(3):
        c = await _seed_published_course(
            db_session,
            owner_id=teacher.id,
            title=f"Course {i}",
            slug=f"today-{i}-{uuid.uuid4().hex[:6]}",
            overview="o",
            lesson_bodies=["body"],
        )
        slugs.append(c.slug)
        await ingest_course(db_session, c.id)
    _install_provider(
        monkeypatch,
        [_valid_plan_json(slugs=slugs, next_action_slug=slugs[0])],
    )
    await learning_path_service.build_path(db_session, user_id=learner.id, goal="goal")
    out = await learning_path_service.get_today_action(db_session, user_id=learner.id)
    assert out is not None
    assert out["course_slug"] == slugs[0]
    assert out["kind"] == "start_lesson"
    assert "due_review_count" in out
