"""S5.7 — LLMContext + resolve_context + build_provider (the only decrypt site).

DB-backed (runs at make test.api). Covers: platform-context invariants,
no-credential → platform, active credential → byok with the user's model on
the registry-fixed base, the decrypt-locus spy (decrypt only in
build_provider), drift → platform+needs_attention (R-M11'), disabled/
soft-deleted → platform, and background ctx → platform (R-S1'').
"""

from __future__ import annotations

import pytest

from app.core import secrets_crypto
from app.core.config import get_settings
from app.models.llm_call import SYSTEM_USER_ID
from app.models.user_llm_credential import (
    VALIDATION_NEEDS_ATTENTION,
    VALIDATION_VALID,
    UserLLMCredential,
)
from app.services import byok
from app.services.byok import PLATFORM_CONTEXT, LLMContext, build_provider, resolve_context
from app.services.llm import AnthropicProvider, OpenAIProvider

SENTINEL_KEY = "sk-BYOK-RESOLVE-SENTINEL-abcdef0123"


@pytest.fixture(autouse=True)
def _byok_on(monkeypatch):
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "true")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    yield
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


async def _store(
    db,
    user_id,
    *,
    provider="openai",
    model="gpt-4o-mini",
    active=True,
    enabled=True,
    fallback=True,
    status=VALIDATION_VALID,
    key=SENTINEL_KEY,
):
    blob = secrets_crypto.encrypt(key.encode())
    cred = UserLLMCredential(
        user_id=user_id,
        provider=provider,
        model=model,
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint(key),
        last4=secrets_crypto.last4(key),
        is_active=active,
        enabled=enabled,
        allow_platform_fallback=fallback,
        last_validation_status=status,
    )
    db.add(cred)
    await db.flush()
    return cred


def test_platform_context_invariants() -> None:
    assert PLATFORM_CONTEXT.user_id == SYSTEM_USER_ID
    assert PLATFORM_CONTEXT.foreground is False
    assert PLATFORM_CONTEXT.credential_id is None


@pytest.mark.asyncio
async def test_no_credential_resolves_to_platform(db_session, make_user) -> None:
    user = await make_user()
    ctx = await resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id is None
    _provider, mode = await build_provider(db_session, ctx)
    assert mode == "platform"


@pytest.mark.asyncio
async def test_active_credential_resolves_to_byok(db_session, make_user) -> None:
    user = await make_user()
    await _store(db_session, user.id, provider="groq", model="llama-3.3-70b-versatile")
    ctx = await resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id is not None
    assert ctx.mode == "byok"
    provider, mode = await build_provider(db_session, ctx)
    assert mode == "byok"
    assert isinstance(provider, OpenAIProvider)  # groq uses openai transport
    assert provider._model == "llama-3.3-70b-versatile"
    assert provider._api_base == "https://api.groq.com/openai/v1"
    # the decrypted key reached the provider (read via the redaction-aware accessor)
    assert provider._key_value() == SENTINEL_KEY


@pytest.mark.asyncio
async def test_decrypt_locus_only_in_build_provider(db_session, make_user, monkeypatch) -> None:
    """The spy: decrypt is called inside build_provider, never resolve_context."""
    user = await make_user()
    await _store(db_session, user.id, provider="openai", model="gpt-4o-mini")

    calls = {"n": 0}
    real_decrypt = secrets_crypto.decrypt

    def _spy(blob):
        calls["n"] += 1
        return real_decrypt(blob)

    monkeypatch.setattr(secrets_crypto, "decrypt", _spy)
    # Also patch the name byok imported.
    monkeypatch.setattr(byok.secrets_crypto, "decrypt", _spy)

    ctx = await resolve_context(db_session, user_id=user.id)
    assert calls["n"] == 0, "resolve_context must NOT decrypt"

    await build_provider(db_session, ctx)
    assert calls["n"] == 1, "build_provider decrypts exactly once"


@pytest.mark.asyncio
async def test_anthropic_credential_builds_anthropic(db_session, make_user) -> None:
    user = await make_user()
    await _store(db_session, user.id, provider="anthropic", model="claude-sonnet-4-6")
    ctx = await resolve_context(db_session, user_id=user.id)
    provider, mode = await build_provider(db_session, ctx)
    assert mode == "byok"
    assert isinstance(provider, AnthropicProvider)
    assert provider._api_base == "https://api.anthropic.com"


@pytest.mark.asyncio
async def test_model_drift_with_fallback_goes_platform_and_marks_needs_attention(
    db_session, make_user
) -> None:
    user = await make_user()
    cred = await _store(db_session, user.id, provider="openai", model="gpt-RETIRED", fallback=True)
    ctx = LLMContext(user_id=user.id, credential_id=cred.id, foreground=True, mode="byok")
    _provider, mode = await build_provider(db_session, ctx)
    assert mode == "platform"
    await db_session.refresh(cred)
    assert cred.last_validation_status == VALIDATION_NEEDS_ATTENTION


@pytest.mark.asyncio
async def test_model_drift_without_fallback_hard_fails(db_session, make_user) -> None:
    from app.core.errors import ByokModelUnavailableError

    user = await make_user()
    cred = await _store(db_session, user.id, provider="openai", model="gpt-RETIRED", fallback=False)
    ctx = LLMContext(user_id=user.id, credential_id=cred.id, foreground=True, mode="byok")
    with pytest.raises(ByokModelUnavailableError):
        await build_provider(db_session, ctx)


@pytest.mark.asyncio
async def test_disabled_credential_resolves_to_platform(db_session, make_user) -> None:
    user = await make_user()
    await _store(db_session, user.id, provider="openai", enabled=False)
    ctx = await resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id is None  # disabled is filtered at resolve
    _, mode = await build_provider(db_session, ctx)
    assert mode == "platform"


@pytest.mark.asyncio
async def test_soft_deleted_credential_resolves_to_platform(db_session, make_user) -> None:
    from datetime import UTC, datetime

    user = await make_user()
    cred = await _store(db_session, user.id, provider="openai")
    cred.deleted_at = datetime.now(UTC)
    await db_session.flush()
    ctx = await resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id is None


@pytest.mark.asyncio
async def test_background_context_is_platform_regardless(db_session, make_user) -> None:
    """R-S1'' — a background ctx never uses BYOK even if a cred id is set."""
    user = await make_user()
    cred = await _store(db_session, user.id, provider="openai")
    bg = LLMContext(user_id=user.id, credential_id=cred.id, foreground=False, mode="byok")
    _, mode = await build_provider(db_session, bg)
    assert mode == "platform"


@pytest.mark.asyncio
async def test_flag_off_resolves_platform(db_session, make_user, monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "false")
    get_settings.cache_clear()
    user = await make_user()
    await _store(db_session, user.id, provider="openai")
    ctx = await resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id is None
    _, mode = await build_provider(db_session, ctx)
    assert mode == "platform"


@pytest.mark.asyncio
async def test_capabilities_can_use_byok(make_user) -> None:
    from app.services.capabilities import can_use_byok

    active = await make_user()
    assert can_use_byok(active) is True
    active.is_active = False
    assert can_use_byok(active) is False
