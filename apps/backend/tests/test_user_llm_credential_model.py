"""S5.3 — user_llm_credentials model + constraints (+ S5.5 credential_id FK).

DB-backed; runs at ``make test.api``. The schema is built from
``Base.metadata.create_all`` (conftest), so these prove the ORM-declared
columns/constraints, which the migration 0038/0040 mirror.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.core import secrets_crypto
from app.models.tutor_turn_job import TutorTurnJob
from app.models.user_llm_credential import UserLLMCredential


async def _make_cred(db, user_id: str, *, provider="openai", model="gpt-4o-mini", active=False):
    blob = secrets_crypto.encrypt(b"sk-credential-plaintext-1234")
    cred = UserLLMCredential(
        user_id=user_id,
        provider=provider,
        model=model,
        enc_blob=blob,
        key_version=1,
        key_fingerprint=secrets_crypto.key_fingerprint("sk-credential-plaintext-1234"),
        last4="1234",
        is_active=active,
    )
    db.add(cred)
    await db.flush()
    return cred


def test_no_plaintext_or_url_columns() -> None:
    cols = {c.name for c in inspect(UserLLMCredential).columns}
    # Envelope + masked metadata present.
    assert {"enc_blob", "key_version", "key_fingerprint", "last4"} <= cols
    # No plaintext / no URL-ish column, ever.
    forbidden = {"api_key", "apikey", "key", "secret", "api_base", "base_url", "host", "url"}
    assert not (forbidden & cols), f"forbidden columns present: {forbidden & cols}"


def test_status_and_flag_defaults_declared() -> None:
    cols = {c.name: c for c in inspect(UserLLMCredential).columns}
    assert cols["last_validation_status"].server_default is not None
    assert cols["enabled"].server_default is not None
    assert cols["is_active"].server_default is not None
    assert cols["allow_platform_fallback"].server_default is not None
    assert cols["deleted_at"].nullable is True


@pytest.mark.asyncio
async def test_one_live_credential_per_provider(db_session, make_user) -> None:
    user = await make_user()
    await _make_cred(db_session, user.id, provider="openai")
    await db_session.commit()
    # Second LIVE openai credential -> partial-unique violation. The
    # violation surfaces at the helper's flush (asyncpg raises on INSERT),
    # not at commit — S5 merge-gate fix.
    with pytest.raises(IntegrityError):
        await _make_cred(db_session, user.id, provider="openai")
    await db_session.rollback()


@pytest.mark.asyncio
async def test_soft_deleted_frees_the_provider_slot(db_session, make_user) -> None:
    user = await make_user()
    first = await _make_cred(db_session, user.id, provider="openai")
    await db_session.commit()
    # Soft-delete the first, then a new live one is allowed.
    from datetime import UTC, datetime

    first.deleted_at = datetime.now(UTC)
    await db_session.commit()
    await _make_cred(db_session, user.id, provider="openai")
    await db_session.commit()  # no IntegrityError
    rows = (
        (
            await db_session.execute(
                select(UserLLMCredential).where(UserLLMCredential.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_at_most_one_active_per_user(db_session, make_user) -> None:
    user = await make_user()
    await _make_cred(db_session, user.id, provider="openai", active=True)
    await db_session.commit()
    # Second ACTIVE credential -> partial-unique violation at the helper's
    # flush (asyncpg raises on INSERT), not at commit — S5 merge-gate fix.
    with pytest.raises(IntegrityError):
        await _make_cred(db_session, user.id, provider="anthropic", active=True)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_user_delete_cascades(db_session, make_user) -> None:
    user = await make_user()
    await _make_cred(db_session, user.id, provider="openai")
    await db_session.commit()
    await db_session.delete(user)
    await db_session.commit()
    rows = (
        (
            await db_session.execute(
                select(UserLLMCredential).where(UserLLMCredential.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


# ----- S5.5: tutor_turn_jobs.credential_id FK SET NULL -----


@pytest.mark.asyncio
async def test_credential_id_set_null_on_credential_delete(db_session, make_user) -> None:
    user = await make_user()
    cred = await _make_cred(db_session, user.id, provider="openai")
    await db_session.commit()
    turn = TutorTurnJob(user_id=user.id, status="pending", credential_id=cred.id)
    db_session.add(turn)
    await db_session.commit()
    # Hard-delete the credential -> turn survives, credential_id nulled.
    await db_session.delete(cred)
    await db_session.commit()
    await db_session.refresh(turn)
    assert turn.credential_id is None
    assert turn.status == "pending"
