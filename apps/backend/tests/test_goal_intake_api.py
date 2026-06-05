"""S3.4 — goal-intake REST surface (/ai/goal/start|turn|finalize).

RequireAuthor, rate-limited, metered. Auth matrix: 401 anonymous, denied for a
suspended user (the landed S1 deps drop is_active=False at get_current_user, so
401/403 — mirrors test_ai_authoring's suspended idiom), 200 for an active user.
Cross-user finalize/turn → 404 (existence-hide). The error envelope is
{error:{code,...}} via AppError subclasses.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import update

from app.core.config import get_settings
from app.models.user import User
from app.services import byok as byok_service
from app.services import learning_brief as svc
from app.services import llm as llm_service

pytestmark = pytest.mark.asyncio


class _ScriptedProvider:
    name = "scripted"
    _model = "scripted-llama"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

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
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _install_provider(monkeypatch, replies):
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    monkeypatch.setattr(svc.llm_service, "get_provider", lambda: prov)
    monkeypatch.setattr(byok_service.llm_service, "get_provider", lambda: prov)
    return prov


def _reply(msg, **fields):
    return json.dumps({"assistant_message": msg, **fields})


# --------------------------------------------------------------------------- #
# POST /ai/goal/start
# --------------------------------------------------------------------------- #


async def test_start_anonymous_401(client, monkeypatch):
    prov = _install_provider(monkeypatch, [])  # must not be called
    r = await client.post("/api/v1/ai/goal/start", json={"goal": "learn react"})
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth.required"
    assert prov.calls == []  # no LLM call for an anonymous caller


async def test_start_suspended_denied_no_llm(
    client, db_session, auth_headers, make_user, monkeypatch
):
    """A suspended user is denied and the provider is never called.

    Landed S1 deps drop is_active=False at get_current_user (401); the capability
    predicate also denies (403). Either way the door is shut and no spend occurs —
    mirrors test_ai_authoring's suspended assertion idiom.
    """
    prov = _install_provider(monkeypatch, [])
    # Build a user, then suspend them, then log them in fresh would 401 — instead
    # log in first, then suspend, so the token is valid but the account is gone.
    import uuid

    from app.core.security import hash_password

    email = f"susp-{uuid.uuid4().hex[:8]}@lumen.test"
    user = await make_user(email=email, password="Password!1234")
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password!1234"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db_session.commit()

    r = await client.post("/api/v1/ai/goal/start", json={"goal": "learn react"}, headers=headers)
    assert r.status_code in (401, 403), r.text
    assert prov.calls == []
    _ = hash_password  # keep import meaningful


async def test_start_active_user_200_returns_session(client, auth_headers, monkeypatch):
    _install_provider(monkeypatch, [_reply("What's your level?", level="beginner")])
    headers = await auth_headers()

    r = await client.post(
        "/api/v1/ai/goal/start", json={"goal": "I want to get good at React"}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"]
    assert body["assistant_message"] == "What's your level?"
    assert body["turns_used"] == 1
    assert body["turns_remaining"] == get_settings().define_elicitation_max_turns - 1
    assert body["converged"] is False
    # The running brief is non-sensitive only — no raw goal echoed back.
    assert "goal" not in body["accumulated_brief"]


async def test_start_empty_goal_422(client, auth_headers, monkeypatch):
    _install_provider(monkeypatch, [])
    headers = await auth_headers()
    r = await client.post("/api/v1/ai/goal/start", json={"goal": ""}, headers=headers)
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# POST /ai/goal/{session}/turn
# --------------------------------------------------------------------------- #


async def test_turn_advances(client, auth_headers, monkeypatch):
    _install_provider(
        monkeypatch,
        [_reply("Hi"), _reply("Noted", level="intermediate")],
    )
    headers = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "learn go"}, headers=headers)
    sid = start.json()["session_id"]

    r = await client.post(
        f"/api/v1/ai/goal/{sid}/turn", json={"message": "intermediate"}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["turns_used"] == 2
    assert body["accumulated_brief"]["level"] == "intermediate"


async def test_turn_cap_returns_envelope_code(client, auth_headers, monkeypatch):
    cap = get_settings().define_elicitation_max_turns
    _install_provider(monkeypatch, [_reply("t", goal_summary=f"s{i}") for i in range(cap)])
    headers = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "learn x"}, headers=headers)
    sid = start.json()["session_id"]

    for _ in range(cap - 1):
        rr = await client.post(
            f"/api/v1/ai/goal/{sid}/turn", json={"message": "more"}, headers=headers
        )
        assert rr.status_code == 200, rr.text

    over = await client.post(
        f"/api/v1/ai/goal/{sid}/turn", json={"message": "one more"}, headers=headers
    )
    assert over.status_code == 429, over.text
    assert over.json()["error"]["code"] == "define.turn_cap"


async def test_turn_cross_user_404(client, auth_headers, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    owner = await auth_headers()
    other = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "mine"}, headers=owner)
    sid = start.json()["session_id"]

    r = await client.post(f"/api/v1/ai/goal/{sid}/turn", json={"message": "x"}, headers=other)
    assert r.status_code == 404, r.text


async def test_turn_anonymous_401(client, monkeypatch):
    _install_provider(monkeypatch, [])
    r = await client.post("/api/v1/ai/goal/sess123/turn", json={"message": "x"})
    assert r.status_code == 401, r.text


# --------------------------------------------------------------------------- #
# POST /ai/goal/{session}/finalize
# --------------------------------------------------------------------------- #


async def test_finalize_returns_brief_out_with_id(client, auth_headers, monkeypatch):
    _install_provider(
        monkeypatch,
        [
            _reply(
                "ready",
                level="advanced",
                time_budget_hours=30,
                prior_knowledge="solid",
                desired_outcomes=["ship a service"],
            )
        ],
    )
    headers = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "learn k8s"}, headers=headers)
    sid = start.json()["session_id"]

    r = await client.post(f"/api/v1/ai/goal/{sid}/finalize", json={}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == sid  # UC-3: response carries the brief id
    assert body["level"] == "advanced"
    assert body["finalized_at"] is not None
    # FR-PRIV-01: no raw goal / ciphertext in the finalized response.
    assert "goal" not in body
    assert "source_goal_enc" not in body


async def test_finalize_cross_user_404(client, auth_headers, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    owner = await auth_headers()
    other = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "mine"}, headers=owner)
    sid = start.json()["session_id"]

    r = await client.post(f"/api/v1/ai/goal/{sid}/finalize", json={}, headers=other)
    assert r.status_code == 404, r.text


async def test_double_finalize_422(client, auth_headers, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    headers = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "g"}, headers=headers)
    sid = start.json()["session_id"]

    first = await client.post(f"/api/v1/ai/goal/{sid}/finalize", json={}, headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post(f"/api/v1/ai/goal/{sid}/finalize", json={}, headers=headers)
    assert second.status_code == 422, second.text
    assert second.json()["error"]["code"] == "define.brief_finalized"


async def test_finalize_applies_edits(client, auth_headers, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok", level="beginner", time_budget_hours=5)])
    headers = await auth_headers()
    start = await client.post("/api/v1/ai/goal/start", json={"goal": "g"}, headers=headers)
    sid = start.json()["session_id"]

    r = await client.post(
        f"/api/v1/ai/goal/{sid}/finalize",
        json={"edits": {"level": "advanced", "time_budget_hours": 40}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["level"] == "advanced"
    assert r.json()["time_budget_hours"] == 40
