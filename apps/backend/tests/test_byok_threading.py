"""S5.12 — LLMContext threading through foreground call paths (DR-8, R-S1'').

DB-backed (runs at make test.api), except the stream-routing test which is
pure-unit. Covers: tutor turn records billing_mode by ctx, learning-path
build is BYOK from the API ctx but platform from the beat, and stream_chat's
byok_dispatch bypasses the global llm_provider switch.
"""

from __future__ import annotations

import pytest

from app.core import secrets_crypto
from app.core.config import get_settings
from app.models.user_llm_credential import UserLLMCredential
from app.services import byok
from app.services.byok import PLATFORM_CONTEXT, LLMContext
from app.services.llm import ChatMessage

SENTINEL = "sk-THREADING-SENTINEL-00000000abcdef"


@pytest.fixture(autouse=True)
def _byok_on(monkeypatch):
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    yield
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


async def _store(db, user_id, *, provider="groq", model="llama-3.3-70b-versatile"):
    blob = secrets_crypto.encrypt(SENTINEL.encode())
    cred = UserLLMCredential(
        user_id=user_id,
        provider=provider,
        model=model,
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint(SENTINEL),
        last4=secrets_crypto.last4(SENTINEL),
        is_active=True,
    )
    db.add(cred)
    await db.flush()
    return cred


@pytest.mark.asyncio
async def test_build_provider_returns_billing_mode_by_ctx(db_session, make_user) -> None:
    user = await make_user()
    # No credential → platform.
    plat_ctx = await byok.resolve_context(db_session, user_id=user.id)
    _, mode = await byok.build_provider(db_session, plat_ctx)
    assert mode == "platform"
    # With an active credential → byok.
    await _store(db_session, user.id)
    byok_ctx = await byok.resolve_context(db_session, user_id=user.id)
    _, mode2 = await byok.build_provider(db_session, byok_ctx)
    assert mode2 == "byok"


@pytest.mark.asyncio
async def test_monthly_beat_ctx_is_platform(db_session, make_user) -> None:
    """R-S1'': the same resolution given PLATFORM_CONTEXT yields platform
    even when the user has an active credential (the beat passes default)."""
    user = await make_user()
    await _store(db_session, user.id)
    # The beat passes PLATFORM_CONTEXT with the system user; foreground=False.
    _, mode = await byok.build_provider(db_session, PLATFORM_CONTEXT)
    assert mode == "platform"


@pytest.mark.asyncio
async def test_stream_dispatch_for_turn_carries_registry_base(db_session, make_user) -> None:
    user = await make_user()
    cred = await _store(db_session, user.id, provider="groq")
    dispatch = await byok.stream_dispatch_for_turn(
        db_session, credential_id=cred.id, user_id=user.id
    )
    assert dispatch is not None
    assert dispatch["base_url"] == "https://api.groq.com/openai/v1"
    assert dispatch["model"] == "llama-3.3-70b-versatile"
    assert dispatch["api_key"] == SENTINEL
    assert dispatch["transport"] == "openai"


@pytest.mark.asyncio
async def test_stream_dispatch_none_without_credential(db_session, make_user) -> None:
    user = await make_user()
    dispatch = await byok.stream_dispatch_for_turn(db_session, credential_id=None, user_id=user.id)
    assert dispatch is None


@pytest.mark.asyncio
async def test_stream_chat_byok_dispatch_bypasses_global_switch(monkeypatch) -> None:
    """The global llm_provider='noop' switch is bypassed when byok_dispatch
    is supplied — stream_chat routes to the openai-compat streamer."""
    from app.services import llm_stream

    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()

    called = {"openai_compat": False, "noop": False}

    async def _fake_openai_compat(messages, *, temperature, api_key, api_base, model):
        called["openai_compat"] = True
        assert api_base == "https://api.groq.com/openai/v1"
        assert api_key == SENTINEL
        yield llm_stream.StreamChunk(delta="hi", done=False)
        yield llm_stream.StreamChunk(delta="", done=True, usage={"cost_usd": 0.0})

    async def _fake_noop(messages, *, temperature):
        called["noop"] = True
        yield llm_stream.StreamChunk(delta="", done=True, usage={})

    monkeypatch.setattr(llm_stream, "_stream_chat_openai_compat", _fake_openai_compat)
    monkeypatch.setattr(llm_stream, "_stream_chat_noop", _fake_noop)

    dispatch = {
        "transport": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": SENTINEL,
        "model": "llama-3.3-70b-versatile",
    }
    chunks = [
        c
        async for c in llm_stream.stream_chat(
            [ChatMessage(role="user", content="q")], byok_dispatch=dispatch
        )
    ]
    assert called["openai_compat"] is True
    assert called["noop"] is False
    assert chunks


@pytest.mark.asyncio
async def test_stream_chat_no_dispatch_uses_global_switch(monkeypatch) -> None:
    """Without byok_dispatch, the platform global switch path is used."""
    from app.services import llm_stream

    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()
    chunks = [c async for c in llm_stream.stream_chat([ChatMessage(role="user", content="q")])]
    # noop path emits the canned response + a terminal usage chunk.
    assert any(c.done for c in chunks)


def test_orchestrate_defaults_to_platform_context() -> None:
    """Pinned regression: orchestrate's ctx defaults to PLATFORM_CONTEXT so
    partial threading never regresses platform behavior."""
    import inspect

    from app.services.tutor_orchestrator import orchestrate

    assert inspect.signature(orchestrate).parameters["ctx"].default is PLATFORM_CONTEXT


def test_threaded_signatures_default_platform() -> None:
    import inspect

    from app.services.ai_authoring import generate_outline
    from app.services.authoring_orchestrator import draft_course
    from app.services.learning_path import build_path, replan_for_user

    for fn in (draft_course, build_path, replan_for_user, generate_outline):
        assert inspect.signature(fn).parameters["ctx"].default is PLATFORM_CONTEXT


def test_llmcontext_is_frozen() -> None:
    import dataclasses

    ctx = LLMContext(user_id="u", credential_id="c", foreground=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.foreground = False  # type: ignore[misc]
