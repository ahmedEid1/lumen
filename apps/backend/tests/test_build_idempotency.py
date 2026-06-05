"""S3.7 — idempotent + concurrency-capped + quota'd self-serve build.

* A second submit for the same ``brief_id`` while the first build still holds the
  per-user advisory lock → ``define.build_in_flight`` (409); no duplicate build.
* A replay (the brief already built a live, non-failed course) returns the SAME
  course without re-running the pipeline (no second LLM spend).
* The per-user concurrency cap (default 1) → ``define.build_in_flight``.
* The per-user daily build quota (non-dollar) → ``define.build_quota`` (429),
  consumed only on a successful build START.
* Suspended/anonymous are denied at the endpoint with no build.

The build is synchronous in-request, so "concurrency" is exercised by holding the
per-user advisory lock in a SEPARATE DB connection and asserting the in-request
build refuses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import DefineBuildInFlightError, DefineBuildQuotaError
from app.models.course import Subject
from app.models.learning_brief import LearningBrief
from app.models.user import Role, User
from app.repositories import audit as audit_repo
from app.services import build as build_service
from app.services import llm as llm_service

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


_OUTLINE = {
    "title": "Go Basics",
    "overview": "An intro.",
    "modules": [
        {
            "title": "Setup",
            "lessons": [{"title": "Install", "type": "text"}, {"title": "Quiz", "type": "quiz"}],
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


# ---------- Replay (idempotency) ----------


async def test_replay_returns_same_course_no_second_build(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)

    prov = _install_provider(monkeypatch, _happy_queue())
    first = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    calls_after_first = len(prov.calls)
    assert calls_after_first > 0

    # Second submit for the SAME brief — the live course already exists, so the
    # build replays (returns the same course id) WITHOUT a second LLM run.
    prov2 = _install_provider(monkeypatch, [])  # would raise if any call lands
    second = await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)
    assert second.course_id == first.course_id
    assert prov2.calls == []


# ---------- In-flight concurrency cap ----------


async def test_in_flight_lock_blocks_second_build(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """Holding the per-user build advisory lock on a separate connection makes the
    in-request build refuse with define.build_in_flight (FR-DEFINE-13/15)."""
    from app.db.base import get_sessionmaker

    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    _install_provider(monkeypatch, [])  # must not run — we refuse before the LLM

    # Acquire the same per-user build lock on a separate session/connection.
    holder_sm = get_sessionmaker()
    async with holder_sm() as holder, holder.begin():
        got = await build_service._try_acquire_build_lock(holder, user.id)
        assert got is True  # the holder owns it
        with pytest.raises(DefineBuildInFlightError):
            await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)


# ---------- Daily quota ----------


async def test_daily_quota_exhausted(db_session: AsyncSession, make_user, monkeypatch) -> None:
    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    brief = await _finalized_brief(db_session, owner_id=user.id)
    _install_provider(monkeypatch, [])

    # Seed exactly the quota's worth of recent course.built audit rows.
    cap = get_settings().define_build_quota_24h
    for _ in range(cap):
        await audit_repo.record(
            db_session, actor_id=user.id, action="course.built", target_type="course", target_id="x"
        )
    await db_session.commit()

    with pytest.raises(DefineBuildQuotaError):
        await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)


async def test_quota_not_charged_on_validation_reject(
    db_session: AsyncSession, make_user, monkeypatch
) -> None:
    """A not-finalized brief is rejected WITHOUT writing a course.built audit row
    (quota consumed only on a successful start, FR-DEFINE-15)."""
    from sqlalchemy import func, select

    from app.models.audit import AuditEvent

    user = await make_user(role=Role.instructor)
    await _personal_subject(db_session)
    # Un-finalized brief.
    brief = LearningBrief(
        owner_id=user.id,
        source_goal_enc=secrets_crypto.encrypt(b"x"),
        goal_summary="x",
        finalized_at=None,
    )
    db_session.add(brief)
    await db_session.commit()
    await db_session.refresh(brief)
    _install_provider(monkeypatch, [])

    from app.core.errors import DefineBriefNotFinalizedError

    with pytest.raises(DefineBriefNotFinalizedError):
        await build_service.build_from_brief(db_session, user=user, brief_id=brief.id)

    built = (
        await db_session.execute(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.actor_id == user.id, AuditEvent.action == "course.built"
            )
        )
    ).scalar_one()
    assert built == 0


# ---------- Endpoint auth matrix ----------


async def test_endpoint_anonymous_401(client, monkeypatch) -> None:
    _install_provider(monkeypatch, [])
    r = await client.post("/api/v1/ai/courses/draft", json={"brief_id": "x"})
    assert r.status_code == 401, r.text


async def test_endpoint_active_user_builds(client, db_session, auth_headers, monkeypatch) -> None:
    _install_provider(monkeypatch, _happy_queue())
    # Create the personal subject + a finalized brief for the logged-in user.
    await _personal_subject(db_session)
    headers = await auth_headers()
    # Resolve the user id from the token via /me.
    me = await client.get("/api/v1/auth/me", headers=headers)
    uid = me.json()["id"]
    brief = await _finalized_brief(db_session, owner_id=uid)

    r = await client.post("/api/v1/ai/courses/draft", json={"brief_id": brief.id}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["course_id"]
    assert body["draft_id"]


async def test_endpoint_suspended_denied(client, db_session, make_user, monkeypatch) -> None:
    _install_provider(monkeypatch, [])
    import uuid

    email = f"susp-{uuid.uuid4().hex[:8]}@lumen.test"
    user = await make_user(email=email, password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password!1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db_session.commit()

    r = await client.post(
        "/api/v1/ai/courses/draft", json={"brief_id": "anything"}, headers=headers
    )
    assert r.status_code in (401, 403), r.text


# silence unused-import lint for timedelta (kept for symmetry with other suites)
_ = timedelta
