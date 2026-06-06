"""S5 gate fixes — ADR-0027 §4 item 3/4 dispatch semantics + the
platform-dollar-guard billing_mode filter.

Covers (Gate-A/Gate-B findings):
- auth-class BYOK dispatch failure marks the credential invalid and, with
  ``allow_platform_fallback`` consent, retries THIS request on the platform
  model (billed platform);
- without consent it raises the redacted ``ByokProviderError`` (never the
  vendor's raw error);
- transient errors re-raise as-is — no fallback, credential untouched
  (item 4: cost ownership stays predictable);
- BYOK rows' real informational cost no longer trips the PLATFORM dollar
  budget (the guard sums platform rows only).

DB-backed (runs at make test.api).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import BudgetExceededError, ByokProviderError
from app.models.llm_call import BILLING_BYOK, BILLING_PLATFORM, STATUS_OK, LLMCall
from app.models.user_llm_credential import (
    VALIDATION_INVALID,
    VALIDATION_VALID,
    UserLLMCredential,
)
from app.services import byok
from app.services import llm as llm_service
from app.services.llm import ChatMessage, ChatResponse
from app.services.llm_call_log import call_logged

SENTINEL = "sk-FALLBACK-SENTINEL-00000000abcdef"


@pytest.fixture(autouse=True)
def _byok_on(monkeypatch):
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "noop")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    yield
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


class _AuthenticationError(Exception):
    """SDK-shaped: openai/anthropic raise *AuthenticationError* on 401."""


class _ScriptedProvider:
    """Minimal provider whose chat_with_usage raises or answers on cue."""

    name = "scripted"
    _model = "scripted-model"

    def __init__(self, *, raises: BaseException | None = None, text: str = "ok"):
        self._raises = raises
        self._text = text
        self.calls = 0

    async def chat_with_usage(self, messages, temperature: float = 0.2) -> ChatResponse:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return ChatResponse(
            text=self._text, prompt_tokens=2, completion_tokens=2, model=self._model
        )


async def _store_cred(db, user_id, *, fallback: bool) -> UserLLMCredential:
    blob = secrets_crypto.encrypt(SENTINEL.encode())
    cred = UserLLMCredential(
        user_id=user_id,
        provider="groq",
        model="llama-3.3-70b-versatile",
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint(SENTINEL),
        last4=SENTINEL[-4:],
        is_active=True,
        allow_platform_fallback=fallback,
        last_validation_status=VALIDATION_VALID,
    )
    db.add(cred)
    await db.flush()
    return cred


@pytest.mark.asyncio
async def test_auth_error_with_consent_falls_back_to_platform(
    db_session, make_user, monkeypatch
) -> None:
    user = await make_user()
    cred = await _store_cred(db_session, user.id, fallback=True)
    ctx = await byok.resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id == cred.id

    platform = _ScriptedProvider(text="platform says hi")
    monkeypatch.setattr(llm_service, "get_provider", lambda: platform)
    failing = _ScriptedProvider(raises=_AuthenticationError("x-request-id=req_LEAK bad key"))

    resp = await call_logged(
        failing,
        [ChatMessage(role="user", content="q")],
        user_id=user.id,
        feature="test.fallback",
        session=db_session,
        ctx=ctx,
        billing_mode=BILLING_BYOK,
    )

    # The request succeeded on the platform model (consented fallback).
    assert resp.text == "platform says hi"
    assert platform.calls == 1
    # The credential got marked invalid (the one-time notice surface).
    await db_session.refresh(cred)
    assert cred.last_validation_status == VALIDATION_INVALID
    # Two rows: the byok error + the platform retry, attributed correctly.
    from sqlalchemy import select

    rows = (
        (await db_session.execute(select(LLMCall).where(LLMCall.user_id == user.id)))
        .scalars()
        .all()
    )
    by_mode = {(r.billing_mode, r.status) for r in rows}
    assert (BILLING_BYOK, "error") in by_mode
    assert (BILLING_PLATFORM, STATUS_OK) in by_mode


@pytest.mark.asyncio
async def test_auth_error_without_consent_raises_redacted(
    db_session, make_user, monkeypatch
) -> None:
    user = await make_user()
    cred = await _store_cred(db_session, user.id, fallback=False)
    ctx = await byok.resolve_context(db_session, user_id=user.id)

    platform = _ScriptedProvider()
    monkeypatch.setattr(llm_service, "get_provider", lambda: platform)
    failing = _ScriptedProvider(raises=_AuthenticationError("x-request-id=req_LEAKME bad key"))

    with pytest.raises(ByokProviderError) as exc_info:
        await call_logged(
            failing,
            [ChatMessage(role="user", content="q")],
            user_id=user.id,
            feature="test.fallback",
            session=db_session,
            ctx=ctx,
            billing_mode=BILLING_BYOK,
        )

    # Redacted: no vendor request-id leaks; no platform dispatch happened.
    assert "req_LEAKME" not in str(exc_info.value.message)
    assert platform.calls == 0
    await db_session.refresh(cred)
    assert cred.last_validation_status == VALIDATION_INVALID


@pytest.mark.asyncio
async def test_transient_error_no_fallback(db_session, make_user, monkeypatch) -> None:
    user = await make_user()
    cred = await _store_cred(db_session, user.id, fallback=True)
    ctx = await byok.resolve_context(db_session, user_id=user.id)

    platform = _ScriptedProvider()
    monkeypatch.setattr(llm_service, "get_provider", lambda: platform)
    failing = _ScriptedProvider(raises=RuntimeError("connection timed out"))

    with pytest.raises(RuntimeError):
        await call_logged(
            failing,
            [ChatMessage(role="user", content="q")],
            user_id=user.id,
            feature="test.fallback",
            session=db_session,
            ctx=ctx,
            billing_mode=BILLING_BYOK,
        )

    # Item 4: transient errors never fall back and never invalidate the key.
    assert platform.calls == 0
    await db_session.refresh(cred)
    assert cred.last_validation_status == VALIDATION_VALID


@pytest.mark.asyncio
async def test_byok_cost_rows_do_not_trip_platform_budget(
    db_session, make_user, monkeypatch
) -> None:
    """Gate-A fix: BYOK rows persist real informational cost; the platform
    dollar guard must not count them."""
    user = await make_user()
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_user_budget_24h_usd", Decimal("1.00"))

    # Seed BYOK spend far beyond the platform budget.
    for _ in range(3):
        db_session.add(
            LLMCall(
                user_id=user.id,
                feature="test.byok",
                provider="scripted",
                model="scripted-model",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=Decimal("5.00"),
                latency_ms=1,
                status=STATUS_OK,
                billing_mode=BILLING_BYOK,
            )
        )
    await db_session.flush()

    ok_provider = _ScriptedProvider(text="platform fine")
    resp = await call_logged(
        ok_provider,
        [ChatMessage(role="user", content="q")],
        user_id=user.id,
        feature="test.platform",
        session=db_session,
        billing_mode=BILLING_PLATFORM,
    )
    assert resp.text == "platform fine"

    # Sanity: the same spend on PLATFORM rows does trip the guard.
    for _ in range(3):
        db_session.add(
            LLMCall(
                user_id=user.id,
                feature="test.platform",
                provider="scripted",
                model="scripted-model",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=Decimal("5.00"),
                latency_ms=1,
                status=STATUS_OK,
                billing_mode=BILLING_PLATFORM,
            )
        )
    await db_session.flush()

    with pytest.raises(BudgetExceededError):
        await call_logged(
            ok_provider,
            [ChatMessage(role="user", content="q")],
            user_id=user.id,
            feature="test.platform",
            session=db_session,
            billing_mode=BILLING_PLATFORM,
        )


@pytest.mark.asyncio
async def test_platform_budget_does_not_block_byok(db_session, make_user, monkeypatch) -> None:
    """Confirm-round fix: a user who exhausted the FREE platform dollar
    budget and then configured their own key must NOT stay blocked. The
    platform dollar guard runs only for ``billing_mode='platform'`` —
    ``current_spend`` is None for BYOK, so an over-budget PLATFORM history
    no longer wedges the user's own-key dispatch."""
    user = await make_user()
    await _store_cred(db_session, user.id, fallback=False)
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_user_budget_24h_usd", Decimal("1.00"))

    # Seed PLATFORM spend far beyond the (monkeypatched) platform budget.
    for _ in range(3):
        db_session.add(
            LLMCall(
                user_id=user.id,
                feature="test.platform",
                provider="scripted",
                model="scripted-model",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=Decimal("5.00"),
                latency_ms=1,
                status=STATUS_OK,
                billing_mode=BILLING_PLATFORM,
            )
        )
    await db_session.flush()

    # A BYOK call still succeeds — the platform guard is skipped for it.
    ok_provider = _ScriptedProvider(text="byok says hi")
    resp = await call_logged(
        ok_provider,
        [ChatMessage(role="user", content="q")],
        user_id=user.id,
        feature="test.byok",
        session=db_session,
        billing_mode=BILLING_BYOK,
    )
    assert resp.text == "byok says hi"
    assert ok_provider.calls == 1

    # Sanity: the SAME over-budget platform history still trips the guard on
    # a PLATFORM call (so the fix narrowed the guard, didn't disable it).
    with pytest.raises(BudgetExceededError):
        await call_logged(
            _ScriptedProvider(text="platform says hi"),
            [ChatMessage(role="user", content="q")],
            user_id=user.id,
            feature="test.platform",
            session=db_session,
            billing_mode=BILLING_PLATFORM,
        )
