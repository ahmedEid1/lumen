"""S3.3 — elicitation service: bounded convergence + immutable finalize + quota.

Runs against real Postgres (conftest). The LLM is a deterministic
``_ScriptedProvider`` returning canned JSON, monkeypatched in via
``llm_service.get_provider`` (which ``byok.build_provider`` calls on the
platform path) — so the metered ``call_logged`` flow runs end-to-end without a
network call.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import (
    DefineBriefFinalizedError,
    DefineSessionQuotaError,
    DefineTurnCapError,
)
from app.models.learning_brief import LearningBrief
from app.schemas.learning_brief import BriefDraft, BriefLevel
from app.services import byok as byok_service
from app.services import learning_brief as svc
from app.services import llm as llm_service

pytestmark = pytest.mark.asyncio


class _ScriptedProvider:
    """Plays back a canned queue of JSON replies (one per LLM turn)."""

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
            text=text, prompt_tokens=32, completion_tokens=32, model=self._model
        )


@pytest.fixture(autouse=True)
def _pin_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    monkeypatch.setenv("LLM_COST_TRACKING_ENABLED", "true")
    monkeypatch.setenv("LLM_USER_BUDGET_24H_USD", "100.00")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def _install_provider(monkeypatch, replies: list[str]) -> _ScriptedProvider:
    prov = _ScriptedProvider(replies)
    monkeypatch.setattr(llm_service, "get_provider", lambda: prov)
    monkeypatch.setattr(svc.llm_service, "get_provider", lambda: prov)
    monkeypatch.setattr(byok_service.llm_service, "get_provider", lambda: prov)
    return prov


def _reply(assistant_message: str, **fields) -> str:
    return json.dumps({"assistant_message": assistant_message, **fields})


# --------------------------------------------------------------------------- #
# start_session
# --------------------------------------------------------------------------- #


async def test_start_creates_in_progress_brief_and_encrypts_goal(
    db_session, make_user, monkeypatch
):
    _install_provider(monkeypatch, [_reply("What's your level?", level="beginner")])
    user = await make_user()

    brief, msg = await svc.start_session(db_session, user=user, goal="I want to get good at React")
    await db_session.commit()

    assert brief.finalized_at is None
    assert brief.owner_id == user.id
    assert brief.turns_used == 1
    assert msg == "What's your level?"
    # Goal is field-encrypted; round-trips back to the original plaintext.
    assert secrets_crypto.decrypt(brief.source_goal_enc).decode() == "I want to get good at React"
    # The first-turn structured update merged.
    assert brief.level == "beginner"


async def test_start_does_not_leak_goal_in_log_or_columns(db_session, make_user, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    user = await make_user()
    goal = "SECRET-GOAL-SENTINEL-xyz learn rust"

    brief, _ = await svc.start_session(db_session, user=user, goal=goal)
    await db_session.commit()

    # No structured column holds the raw goal.
    for col in (brief.goal_summary, brief.level, brief.prior_knowledge, brief.suggested_subject):
        assert col is None or goal not in str(col)
    assert goal not in repr(brief)


# --------------------------------------------------------------------------- #
# take_turn — bounded cap + convergence + mutability
# --------------------------------------------------------------------------- #


async def test_turn_mutates_accumulated_fields(db_session, make_user, monkeypatch):
    """Un-finalized briefs are mutable across turns (FR-DEFINE-08)."""
    _install_provider(
        monkeypatch,
        [
            _reply("Hi! What's your level?"),
            _reply("Got it. How many hours?", level="intermediate"),
        ],
    )
    user = await make_user()
    brief, _ = await svc.start_session(db_session, user=user, goal="learn go")
    await db_session.commit()
    assert brief.level is None

    brief, _msg, converged = await svc.take_turn(
        db_session, user=user, session_id=brief.id, message="intermediate"
    )
    await db_session.commit()
    assert brief.level == "intermediate"
    assert brief.turns_used == 2
    assert converged is False


async def test_convergence_when_required_fields_present(db_session, make_user, monkeypatch):
    _install_provider(
        monkeypatch,
        [
            _reply("Starting", level="beginner"),
            _reply(
                "Great, I think I have what I need — review and finalize?",
                time_budget_hours=10,
                prior_knowledge="none",
                desired_outcomes=["Build a CLI tool"],
            ),
        ],
    )
    user = await make_user()
    brief, _ = await svc.start_session(db_session, user=user, goal="learn go")
    await db_session.commit()

    brief, _msg, converged = await svc.take_turn(
        db_session, user=user, session_id=brief.id, message="10 hours, no experience, build a CLI"
    )
    await db_session.commit()
    assert converged is True


async def test_seventh_turn_raises_turn_cap_and_makes_no_llm_call(
    db_session, make_user, monkeypatch
):
    """The (cap+1)th turn raises define.turn_cap and does NOT call the LLM."""
    cap = get_settings().define_elicitation_max_turns
    # start = turn 1; then we need (cap-1) more take_turns to reach the cap,
    # so script start + (cap-1) replies. The cap-th turn must NOT consume a reply.
    replies = [_reply("turn", goal_summary=f"s{i}") for i in range(cap)]
    prov = _install_provider(monkeypatch, replies)
    user = await make_user()

    brief, _ = await svc.start_session(db_session, user=user, goal="learn x")
    await db_session.commit()
    assert brief.turns_used == 1

    # Burn turns 2..cap (cap-1 turns) — all consume a reply.
    for _ in range(cap - 1):
        brief, _m, _c = await svc.take_turn(
            db_session, user=user, session_id=brief.id, message="more"
        )
        await db_session.commit()
    assert brief.turns_used == cap
    calls_before = len(prov.calls)

    # The (cap+1)th take_turn must raise and NOT touch the provider.
    with pytest.raises(DefineTurnCapError):
        await svc.take_turn(db_session, user=user, session_id=brief.id, message="one more")
    assert len(prov.calls) == calls_before  # no LLM call was made


async def test_turn_on_unknown_or_foreign_session_returns_none(db_session, make_user, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok"), _reply("ok2")])
    owner = await make_user()
    other = await make_user()
    brief, _ = await svc.start_session(db_session, user=owner, goal="mine")
    await db_session.commit()

    # Unknown id.
    assert await svc.take_turn(db_session, user=owner, session_id="nope", message="x") is None
    # Another user's session is invisible (existence-hide → None → 404).
    assert await svc.take_turn(db_session, user=other, session_id=brief.id, message="x") is None


# --------------------------------------------------------------------------- #
# finalize — immutability + apply edits once
# --------------------------------------------------------------------------- #


async def test_finalize_stamps_and_persists_fields(db_session, make_user, monkeypatch):
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
    user = await make_user()
    brief, _ = await svc.start_session(db_session, user=user, goal="learn k8s")
    await db_session.commit()

    finalized = await svc.finalize(db_session, user=user, session_id=brief.id)
    await db_session.commit()
    assert finalized is not None
    assert finalized.finalized_at is not None
    assert finalized.level == "advanced"
    assert finalized.time_budget_hours == 30
    assert finalized.desired_outcomes == ["ship a service"]


async def test_finalize_applies_edits_once(db_session, make_user, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok", level="beginner", time_budget_hours=5)])
    user = await make_user()
    brief, _ = await svc.start_session(db_session, user=user, goal="learn sql")
    await db_session.commit()

    edits = BriefDraft(level=BriefLevel.advanced, time_budget_hours=40)
    finalized = await svc.finalize(db_session, user=user, session_id=brief.id, edits=edits)
    await db_session.commit()
    assert finalized.level == "advanced"
    assert finalized.time_budget_hours == 40


async def test_second_finalize_raises_brief_finalized(db_session, make_user, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    user = await make_user()
    brief, _ = await svc.start_session(db_session, user=user, goal="learn rust")
    await db_session.commit()

    first = await svc.finalize(db_session, user=user, session_id=brief.id)
    await db_session.commit()
    stamp = first.finalized_at

    with pytest.raises(DefineBriefFinalizedError):
        await svc.finalize(db_session, user=user, session_id=brief.id)
    # Row unchanged.
    await db_session.refresh(brief)
    assert brief.finalized_at == stamp


async def test_turn_after_finalize_raises_brief_finalized(db_session, make_user, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    user = await make_user()
    brief, _ = await svc.start_session(db_session, user=user, goal="learn ts")
    await db_session.commit()
    await svc.finalize(db_session, user=user, session_id=brief.id)
    await db_session.commit()

    with pytest.raises(DefineBriefFinalizedError):
        await svc.take_turn(db_session, user=user, session_id=brief.id, message="more")


async def test_finalize_foreign_session_returns_none(db_session, make_user, monkeypatch):
    _install_provider(monkeypatch, [_reply("ok")])
    owner = await make_user()
    other = await make_user()
    brief, _ = await svc.start_session(db_session, user=owner, goal="mine")
    await db_session.commit()

    assert await svc.finalize(db_session, user=other, session_id=brief.id) is None


# --------------------------------------------------------------------------- #
# session quota (R-M10)
# --------------------------------------------------------------------------- #


async def test_session_quota_blocks_n_plus_one(db_session, make_user, monkeypatch):
    monkeypatch.setenv("DEFINE_ELICITATION_SESSIONS_24H", "2")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    _install_provider(monkeypatch, [_reply("ok")] * 5)
    user = await make_user()

    # Two sessions are allowed.
    await svc.start_session(db_session, user=user, goal="g1")
    await db_session.commit()
    await svc.start_session(db_session, user=user, goal="g2")
    await db_session.commit()

    # The third in-window is rejected.
    with pytest.raises(DefineSessionQuotaError):
        await svc.start_session(db_session, user=user, goal="g3")

    # Only the two committed briefs exist (the quota tripped before insert).
    n = (
        await db_session.execute(
            select(func.count(LearningBrief.id)).where(LearningBrief.owner_id == user.id)
        )
    ).scalar_one()
    assert n == 2


# --------------------------------------------------------------------------- #
# estimate_counts (FR-DEFINE-16 / DR-4, consumed by S3.6)
# --------------------------------------------------------------------------- #


async def test_estimate_counts_bands():
    assert svc.estimate_counts(3)[0] == 2  # low band
    assert svc.estimate_counts(12)[0] == 4  # mid band
    assert svc.estimate_counts(30)[0] == 6  # high band
    assert svc.estimate_counts(None)[0] == 4  # default to mid
    # Monotonic non-decreasing across bands (low <= mid <= high).
    assert svc.estimate_counts(3)[0] <= svc.estimate_counts(12)[0] <= svc.estimate_counts(30)[0]
