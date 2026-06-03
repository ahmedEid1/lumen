"""S5.14 — rotate_byok_master_key: re-wrap enc_data_key only (FR-BYOK-12, R-S2).

DB-backed (runs at make test.api). Seeds credentials wrapped under KEK v1,
rotates to v2, and asserts every row is now v2, the inner encrypted-plaintext
blob is preserved (decrypts to the original key), and a master-key-rotated
audit event is emitted (counts only — no plaintext).
"""

from __future__ import annotations

import base64
import os

import pytest
from sqlalchemy import func, select

from app.core import secrets_crypto
from app.core.config import get_settings
from app.models.audit import AuditEvent
from app.models.user_llm_credential import UserLLMCredential
from app.services import llm_credentials as svc

KEY_V1 = base64.b64encode(os.urandom(32)).decode()
KEY_V2 = base64.b64encode(os.urandom(32)).decode()
PLAINTEXT = "sk-ROTATION-PLAINTEXT-000000abcdef"


@pytest.fixture
def _kek_v1(monkeypatch):
    """Configure ONLY v1 active so seeded creds are wrapped under v1."""
    monkeypatch.setenv("FEATURE_BYOK_ENABLED", "true")
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1":"{KEY_V1}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "1")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    yield
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


def _set_v2_active(monkeypatch):
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1":"{KEY_V1}","2":"{KEY_V2}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "2")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()


@pytest.mark.asyncio
async def test_rotation_rewraps_dek_only(db_session, make_user, monkeypatch, _kek_v1) -> None:
    # Seed two credentials wrapped under v1.
    creds = []
    for prov in ("openai", "groq"):
        blob = secrets_crypto.encrypt(PLAINTEXT.encode())
        cred = UserLLMCredential(
            user_id=(await make_user()).id,
            provider=prov,
            model="gpt-4o-mini" if prov == "openai" else "llama-3.3-70b-versatile",
            enc_blob=blob,
            key_version=1,
            key_fingerprint=secrets_crypto.key_fingerprint(PLAINTEXT),
            last4=secrets_crypto.last4(PLAINTEXT),
        )
        db_session.add(cred)
        creds.append(cred)
    await db_session.commit()
    original_blobs = {c.id: c.enc_blob for c in creds}

    # Activate v2 (both versions present) and rotate.
    _set_v2_active(monkeypatch)
    rotated, skipped = await svc.rotate_master_key(db_session)
    assert rotated == 2
    assert skipped == 0

    for cred in creds:
        await db_session.refresh(cred)
        assert cred.key_version == 2
        # The blob changed (re-wrapped) ...
        assert cred.enc_blob != original_blobs[cred.id]
        # ... but it still decrypts to the original plaintext (enc_key intact).
        assert secrets_crypto.decrypt(cred.enc_blob).decode() == PLAINTEXT

    # Audit event emitted, counts only, no plaintext.
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "byok.master_key_rotated")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].data["rotated"] == 2
    assert PLAINTEXT not in str(events[0].data)


@pytest.mark.asyncio
async def test_rotation_is_idempotent(db_session, make_user, monkeypatch, _kek_v1) -> None:
    blob = secrets_crypto.encrypt(PLAINTEXT.encode())
    cred = UserLLMCredential(
        user_id=(await make_user()).id,
        provider="openai",
        model="gpt-4o-mini",
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint(PLAINTEXT),
        last4=secrets_crypto.last4(PLAINTEXT),
    )
    db_session.add(cred)
    await db_session.commit()

    _set_v2_active(monkeypatch)
    await svc.rotate_master_key(db_session)
    # Second pass: everything is already on v2 → all skipped.
    rotated2, skipped2 = await svc.rotate_master_key(db_session)
    assert rotated2 == 0
    assert skipped2 == 1


@pytest.mark.asyncio
async def test_rotation_refuses_missing_target_version(
    db_session, make_user, monkeypatch, _kek_v1
) -> None:
    """R-S2: rotating to a version whose KEK is absent must fail loudly
    (secrets_crypto raises) — never silently leave rows half-rotated."""
    blob = secrets_crypto.encrypt(PLAINTEXT.encode())
    cred = UserLLMCredential(
        user_id=(await make_user()).id,
        provider="openai",
        model="gpt-4o-mini",
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint(PLAINTEXT),
        last4=secrets_crypto.last4(PLAINTEXT),
    )
    db_session.add(cred)
    await db_session.commit()

    # Point the active version at 3 but only ship v1 — secrets_crypto._load_keks
    # raises because version 3 has no key.
    monkeypatch.setenv("BYOK_MASTER_KEYS", f'{{"1":"{KEY_V1}"}}')
    monkeypatch.setenv("BYOK_MASTER_KEY_VERSION", "3")
    get_settings.cache_clear()
    secrets_crypto.reset_for_tests()
    rotated_count = (
        await db_session.execute(select(func.count(UserLLMCredential.id)))
    ).scalar_one()
    assert rotated_count == 1
    with pytest.raises(RuntimeError):
        await svc.rotate_master_key(db_session)
