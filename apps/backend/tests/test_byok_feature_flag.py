"""S5.16 — feature_byok_enabled gate (default OFF, ADR-0027 §Migrations).

Ships inert until the KEK is confirmed fleet-wide. Flag OFF → credential
write/resolve paths are inert and resolution is always platform; flag ON →
full BYOK. DB-backed (runs at make test.api); the default-OFF assertion is
pure-unit.
"""

from __future__ import annotations

import uuid

import pytest

from app.core import secrets_crypto
from app.core.config import Settings, get_settings
from app.models.user import Role


def test_flag_defaults_off() -> None:
    # A fresh Settings (no env) has BYOK off — ships inert (R-S2/R-S3).
    assert Settings().feature_byok_enabled is False


@pytest.fixture
def _byok_off(monkeypatch):
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "false")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    yield
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


async def _auth(client, make_user):
    email = f"flag-{uuid.uuid4().hex[:8]}@lumen.test"
    await make_user(email=email, password="Password!1234", role=Role.student)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password!1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_flag_off_credential_write_is_inert(client, make_user, _byok_off) -> None:
    h = await _auth(client, make_user)
    r = await client.put(
        "/api/v1/me/llm-credentials/openai",
        json={"model": "gpt-4o-mini", "api_key": "sk-aaaaaaaaaaaaaaaaaaaa"},
        headers=h,
    )
    # Capability gate denies when the flag is off (403 byok.capability_revoked).
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "byok.capability_revoked"


@pytest.mark.asyncio
async def test_flag_off_resolution_is_platform(db_session, make_user, _byok_off) -> None:
    from app.models.user_llm_credential import UserLLMCredential
    from app.services import byok

    user = await make_user()
    # Even a directly-seeded active credential is ignored when the flag is off.
    blob = secrets_crypto.encrypt(b"sk-seeded-direct-0000")
    db_session.add(
        UserLLMCredential(
            user_id=user.id,
            provider="openai",
            model="gpt-4o-mini",
            enc_blob=blob,
            key_version=1,
            key_fingerprint=secrets_crypto.key_fingerprint("sk-seeded-direct-0000"),
            last4="0000",
            is_active=True,
        )
    )
    await db_session.flush()
    ctx = await byok.resolve_context(db_session, user_id=user.id)
    assert ctx.credential_id is None
    _, mode = await byok.build_provider(db_session, ctx)
    assert mode == "platform"
