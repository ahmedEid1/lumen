"""Authoring trace read endpoint authorisation tests (Lumen v2 Phase I3).

Covers ``GET /api/v1/studio/drafts/{course_id}/trace``:

* Owner instructor sees the trace.
* Admin sees the trace.
* Another instructor gets 403.
* Anonymous gets 401.
* Unknown course id gets 404 (we don't leak existence).
* The orchestrator endpoint itself accepts an instructor body and
  returns the expected shape (smoke; the orchestrator's own tests
  cover the deep cases).
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.course import Subject
from app.models.course_draft_trace import (
    DRAFT_STATUS_OK,
    DRAFT_STEP_RESEARCHER,
    CourseDraftTrace,
)
from app.models.user import Role, User
from app.services import llm as llm_service


class _ScriptedProvider:
    """Pasted from the orchestrator test — kept inline so the two
    files don't share a private helper."""

    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[llm_service.ChatMessage]] = []

    async def chat(self, messages, temperature: float = 0.2) -> str:
        del temperature
        self.calls.append(list(messages))
        if not self._replies:
            raise AssertionError(
                "ScriptedProvider queue exhausted — "
                "test under-scripted the LLM."
            )
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
    monkeypatch.setenv("EMBEDDING_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _install_provider(monkeypatch, replies):
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    from app.services import authoring_orchestrator as orch_mod
    monkeypatch.setattr(orch_mod.llm_service, "get_provider", lambda: prov)
    from app.services import ai_authoring as ai_mod
    monkeypatch.setattr(ai_mod.llm_service, "get_provider", lambda: prov)
    return prov


async def _make_subject(db: AsyncSession) -> Subject:
    suffix = uuid.uuid4().hex[:6]
    s = Subject(title=f"S {suffix}", slug=f"s-{suffix}")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _seed_trace_row(
    db: AsyncSession,
    *,
    user_id: str,
    course_id: str | None = None,
) -> CourseDraftTrace:
    """Directly insert one trace row without running the full orchestrator.

    Lets the auth-shaped tests skip the (expensive, well-tested)
    full pipeline and focus on the read endpoint's gate.
    """
    row = CourseDraftTrace(
        draft_id=uuid.uuid4().hex[:16],
        user_id=user_id,
        course_id=course_id,
        step=DRAFT_STEP_RESEARCHER,
        step_index=0,
        payload={"prompt_summary": "test", "response_summary": "test"},
        status=DRAFT_STATUS_OK,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


_VALID_OUTLINE = {
    "title": "FastAPI",
    "overview": "A focused intro.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [
                {"title": "Install Python 3.13", "type": "text"},
                {"title": "Setup quiz", "type": "quiz"},
            ],
        },
    ],
}


def _critic_json(coverage=5, learning_arc=5, scope=5) -> str:
    return json.dumps(
        {
            "scores": {
                "coverage": coverage,
                "learning_arc": learning_arc,
                "scope": scope,
            },
            "weak_spots": [],
            "rationale": "ok",
        }
    )


_LESSON_DOC = json.dumps(
    {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Body."}],
            }
        ],
    }
)


_QUIZ_JSON = json.dumps(
    {
        "questions": [
            {
                "id": "q1",
                "prompt": "What is FastAPI?",
                "kind": "single",
                "choices": [
                    {"id": "a", "text": "Web framework"},
                    {"id": "b", "text": "Database"},
                ],
                "answer_keys": ["a"],
            }
        ]
    }
)


# ---------- POST /studio/ai/draft-course ----------


async def test_draft_course_smoke(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """The end-to-end endpoint produces a draft + a non-empty trace."""
    headers = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    _install_provider(
        monkeypatch,
        [
            json.dumps(_VALID_OUTLINE),
            _critic_json(),
            _LESSON_DOC,  # lesson 1
            _QUIZ_JSON,  # lesson 2 (quiz)
            _critic_json(coverage=4, learning_arc=4, scope=4),  # final
        ],
    )
    r = await client.post(
        "/api/v1/studio/ai/draft-course",
        json={"brief": "Teach FastAPI.", "subject_slug": subject.slug},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["course_id"]
    assert body["module_count"] == 1
    assert body["lesson_count"] == 2
    assert body["revisions_used"] == 0
    assert body["final_score"]["mean"] == 4.0


async def test_draft_course_requires_instructor(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """A student trying to draft → 403; no LLM call lands."""
    subject = await _make_subject(db_session)
    headers = await auth_headers(role=Role.student)
    prov = _install_provider(monkeypatch, [])
    r = await client.post(
        "/api/v1/studio/ai/draft-course",
        json={"brief": "Teach FastAPI.", "subject_slug": subject.slug},
        headers=headers,
    )
    assert r.status_code == 403, r.text
    assert prov.calls == []


async def test_draft_course_unknown_subject_404(
    client: AsyncClient,
    auth_headers,
    monkeypatch,
) -> None:
    """Unknown subject_slug → 404 before any LLM call."""
    headers = await auth_headers(role=Role.instructor)
    prov = _install_provider(monkeypatch, [])
    r = await client.post(
        "/api/v1/studio/ai/draft-course",
        json={"brief": "Teach.", "subject_slug": "no-such-subject"},
        headers=headers,
    )
    assert r.status_code == 404, r.text
    assert prov.calls == []


# ---------- GET /studio/drafts/{course_id}/trace ----------


async def test_trace_read_owner_sees_steps(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """An owner instructor reads the trace for their own course."""
    headers = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    _install_provider(
        monkeypatch,
        [
            json.dumps(_VALID_OUTLINE),
            _critic_json(),
            _LESSON_DOC,
            _QUIZ_JSON,
            _critic_json(coverage=4, learning_arc=4, scope=4),
        ],
    )
    r = await client.post(
        "/api/v1/studio/ai/draft-course",
        json={"brief": "Teach FastAPI.", "subject_slug": subject.slug},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["course_id"]

    r2 = await client.get(
        f"/api/v1/studio/drafts/{course_id}/trace",
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["course_id"] == course_id
    assert body["draft_id"]
    assert len(body["steps"]) >= 4  # researcher + outliner + critic + final
    step_kinds = [s["step"] for s in body["steps"]]
    assert "researcher" in step_kinds
    assert "outliner" in step_kinds
    assert "final_critic" in step_kinds


async def test_trace_read_other_instructor_forbidden(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    make_user,
    monkeypatch,
) -> None:
    """A different instructor calling against someone else's course → 403."""
    owner_headers = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    _install_provider(
        monkeypatch,
        [
            json.dumps(_VALID_OUTLINE),
            _critic_json(),
            _LESSON_DOC,
            _QUIZ_JSON,
            _critic_json(coverage=4, learning_arc=4, scope=4),
        ],
    )
    r = await client.post(
        "/api/v1/studio/ai/draft-course",
        json={"brief": "Teach FastAPI.", "subject_slug": subject.slug},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["course_id"]

    other_headers = await auth_headers(role=Role.instructor)
    r2 = await client.get(
        f"/api/v1/studio/drafts/{course_id}/trace",
        headers=other_headers,
    )
    assert r2.status_code == 403, r2.text


async def test_trace_read_admin_allowed(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Admin can read any instructor's trace."""
    owner_headers = await auth_headers(role=Role.instructor)
    subject = await _make_subject(db_session)
    _install_provider(
        monkeypatch,
        [
            json.dumps(_VALID_OUTLINE),
            _critic_json(),
            _LESSON_DOC,
            _QUIZ_JSON,
            _critic_json(coverage=4, learning_arc=4, scope=4),
        ],
    )
    r = await client.post(
        "/api/v1/studio/ai/draft-course",
        json={"brief": "Teach FastAPI.", "subject_slug": subject.slug},
        headers=owner_headers,
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["course_id"]

    admin_headers = await auth_headers(role=Role.admin)
    r2 = await client.get(
        f"/api/v1/studio/drafts/{course_id}/trace",
        headers=admin_headers,
    )
    assert r2.status_code == 200, r2.text


async def test_trace_read_anonymous_unauthorized(
    client: AsyncClient,
) -> None:
    """Anonymous → 401."""
    r = await client.get("/api/v1/studio/drafts/anything/trace")
    assert r.status_code == 401, r.text


async def test_trace_read_unknown_course_404(
    client: AsyncClient,
    auth_headers,
) -> None:
    """Unknown course id → 404 (we don't leak existence)."""
    headers = await auth_headers(role=Role.instructor)
    r = await client.get(
        "/api/v1/studio/drafts/does-not-exist/trace", headers=headers
    )
    assert r.status_code == 404, r.text
