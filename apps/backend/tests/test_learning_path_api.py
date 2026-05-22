"""HTTP-level tests for the learning-path endpoints (Phase I5).

Until the orchestrator wires ``learning_path.router`` into
``app.api.router``, these tests attach the router themselves at
fixture-time so we can exercise the wire format independently of
the rest of the API. The mount point matches what the orchestrator
will configure: ``/api/v1/me``.

Coverage:

* ``POST /api/v1/me/learning-path``                          — build a new path; 201 + body.
* ``GET  /api/v1/me/learning-path``                          — fetch / 404 / cross-user isolation.
* ``GET  /api/v1/me/learning-path/today``                    — empty-state and populated.
* ``POST /api/v1/me/learning-path/steps/{id}/complete``      — owner flow, cross-user 404.
* ``POST /api/v1/me/learning-path/replan``                   — 404 with no active path.
* Auth gate — every endpoint 401 without a token.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import learning_path as learning_path_api
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
from app.models.user import Role
from app.services import learning_path as learning_path_service
from app.services import llm as llm_service
from app.services.embeddings_ingest import ingest_course


# ---------- Scripted provider (mirrors service tests) ----------


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


@pytest.fixture
def app_with_learning_path(app):
    """Attach the learning-path router until the orchestrator registers it.

    The fixture mutates the per-test ``app`` instance built by the
    conftest fixture. The conftest's app is created fresh for each
    test (no shared state) so the include is idempotent at the
    suite level.
    """
    app.include_router(
        learning_path_api.router, prefix="/api/v1/me", tags=["learning-path"]
    )
    return app


@pytest.fixture
async def http(app_with_learning_path, client: AsyncClient):
    """Yield the standard client — the router was attached on ``app``."""
    yield client


def _install_provider(
    monkeypatch: pytest.MonkeyPatch, replies: list[str]
) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    return prov


# ---------- Catalog seeding ----------


async def _seed_catalog(
    db: AsyncSession, *, owner_id: str, n: int = 3
) -> list[str]:
    """Create N published courses with one text lesson each; return their slugs."""
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
            slug=f"api-c{i}-{suffix}",
            overview=f"overview {i}",
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
                title=f"Lesson {i}",
                order=0,
                type=LessonType.text,
                data={"type": "text", "body_markdown": f"body {i}"},
            )
        )
        await db.commit()
        await ingest_course(db, course.id)
        slugs.append(course.slug)
    return slugs


def _valid_plan(slugs: list[str], *, next_action_slug: str | None = None) -> str:
    third = max(1, len(slugs) // 3)
    payload: dict = {
        "milestones": [
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
        ],
        "rationale": "A coherent 3-stage sequence.",
    }
    if next_action_slug:
        payload["next_action"] = {
            "course_slug": next_action_slug,
            "kind": "start_lesson",
        }
    return json.dumps(payload)


# ---------- Auth gate ----------


async def test_endpoints_require_authentication(http: AsyncClient) -> None:
    """Every endpoint 401s without a bearer token."""
    r = await http.post(
        "/api/v1/me/learning-path", json={"goal": "be a backend engineer"}
    )
    assert r.status_code == 401
    r = await http.get("/api/v1/me/learning-path")
    assert r.status_code == 401
    r = await http.get("/api/v1/me/learning-path/today")
    assert r.status_code == 401
    r = await http.post("/api/v1/me/learning-path/steps/x/complete")
    assert r.status_code == 401
    r = await http.post("/api/v1/me/learning-path/replan")
    assert r.status_code == 401


# ---------- Build (POST) ----------


async def test_build_returns_201_with_full_path(
    http: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
    make_user,
    monkeypatch,
) -> None:
    teacher = await make_user(role=Role.instructor)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)
    _install_provider(
        monkeypatch, [_valid_plan(slugs, next_action_slug=slugs[0])]
    )
    headers = await auth_headers(role=Role.student)
    r = await http.post(
        "/api/v1/me/learning-path",
        json={"goal": "Become a backend engineer in 6 months"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active"
    assert body["goal"].startswith("Become a backend")
    assert len(body["steps"]) >= 3
    assert body["next_action"]["kind"] == "start_lesson"
    # Each step has stable shape.
    first = body["steps"][0]
    assert "id" in first
    assert "milestone_name" in first
    assert first["status"] == "pending"


async def test_build_validates_request_body(
    http: AsyncClient, auth_headers
) -> None:
    """Empty / overly-short goal is a 422."""
    headers = await auth_headers(role=Role.student)
    r = await http.post(
        "/api/v1/me/learning-path", json={"goal": ""}, headers=headers
    )
    assert r.status_code == 422


# ---------- Get / 404 / cross-user ----------


async def test_get_returns_404_without_active(
    http: AsyncClient, auth_headers
) -> None:
    headers = await auth_headers(role=Role.student)
    r = await http.get("/api/v1/me/learning-path", headers=headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "learning_path.not_found"


async def test_get_returns_caller_path_only(
    http: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
    make_user,
    monkeypatch,
) -> None:
    """Paths are strictly scoped to the calling user."""
    teacher = await make_user(role=Role.instructor)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)
    _install_provider(monkeypatch, [_valid_plan(slugs)])
    owner_headers = await auth_headers(role=Role.student)
    build = await http.post(
        "/api/v1/me/learning-path",
        json={"goal": "Goal A"},
        headers=owner_headers,
    )
    assert build.status_code == 201
    # Owner sees it.
    r = await http.get("/api/v1/me/learning-path", headers=owner_headers)
    assert r.status_code == 200
    assert r.json()["goal"] == "Goal A"
    # Second user has no path.
    intruder_headers = await auth_headers(role=Role.student)
    r2 = await http.get("/api/v1/me/learning-path", headers=intruder_headers)
    assert r2.status_code == 404


# ---------- Today widget ----------


async def test_today_empty_state(
    http: AsyncClient, auth_headers
) -> None:
    """No active path → 200 with all-null fields."""
    headers = await auth_headers(role=Role.student)
    r = await http.get("/api/v1/me/learning-path/today", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["course_slug"] is None
    assert body["kind"] is None
    assert body["due_review_count"] == 0


async def test_today_returns_action_after_build(
    http: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
    make_user,
    monkeypatch,
) -> None:
    teacher = await make_user(role=Role.instructor)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)
    _install_provider(
        monkeypatch, [_valid_plan(slugs, next_action_slug=slugs[1])]
    )
    headers = await auth_headers(role=Role.student)
    build = await http.post(
        "/api/v1/me/learning-path",
        json={"goal": "Goal"},
        headers=headers,
    )
    assert build.status_code == 201
    r = await http.get("/api/v1/me/learning-path/today", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["course_slug"] == slugs[1]
    assert body["kind"] == "start_lesson"
    # ``lesson_id_if_applicable`` was resolved from the catalog.
    assert body["lesson_id_if_applicable"] is not None


# ---------- Complete step ----------


async def test_complete_step_flips_status(
    http: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
    make_user,
    monkeypatch,
) -> None:
    teacher = await make_user(role=Role.instructor)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)
    _install_provider(monkeypatch, [_valid_plan(slugs)])
    headers = await auth_headers(role=Role.student)
    build = await http.post(
        "/api/v1/me/learning-path",
        json={"goal": "Goal"},
        headers=headers,
    )
    step_id = build.json()["steps"][0]["id"]
    r = await http.post(
        f"/api/v1/me/learning-path/steps/{step_id}/complete",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


async def test_complete_step_cross_user_returns_404(
    http: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
    make_user,
    monkeypatch,
) -> None:
    """A step belonging to user A is not findable by user B."""
    teacher = await make_user(role=Role.instructor)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)
    _install_provider(monkeypatch, [_valid_plan(slugs)])
    owner_headers = await auth_headers(role=Role.student)
    build = await http.post(
        "/api/v1/me/learning-path",
        json={"goal": "Goal"},
        headers=owner_headers,
    )
    step_id = build.json()["steps"][0]["id"]
    intruder_headers = await auth_headers(role=Role.student)
    r = await http.post(
        f"/api/v1/me/learning-path/steps/{step_id}/complete",
        headers=intruder_headers,
    )
    assert r.status_code == 404


# ---------- Manual replan ----------


async def test_manual_replan_returns_404_without_active(
    http: AsyncClient, auth_headers
) -> None:
    headers = await auth_headers(role=Role.student)
    r = await http.post("/api/v1/me/learning-path/replan", headers=headers)
    assert r.status_code == 404


async def test_manual_replan_builds_new_active(
    http: AsyncClient,
    db_session: AsyncSession,
    auth_headers,
    make_user,
    monkeypatch,
) -> None:
    teacher = await make_user(role=Role.instructor)
    slugs = await _seed_catalog(db_session, owner_id=teacher.id, n=3)
    _install_provider(
        monkeypatch, [_valid_plan(slugs), _valid_plan(slugs)]
    )
    headers = await auth_headers(role=Role.student)
    build = await http.post(
        "/api/v1/me/learning-path",
        json={"goal": "Goal"},
        headers=headers,
    )
    original_id = build.json()["id"]
    r = await http.post(
        "/api/v1/me/learning-path/replan", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    # The replan produces a new path id.
    assert r.json()["id"] != original_id
