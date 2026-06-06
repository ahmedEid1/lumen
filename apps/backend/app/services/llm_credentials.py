"""BYOK credential service — upsert/patch/delete/validate (S5.9 / ADR-0027 §6).

The only place credential key material is encrypted (via the foundation
``secrets_crypto``) and the only validate-probe caller. Reads are masked at
the schema edge; this service never returns key bytes. Audit events
(create/update/delete/validate, status-only) are emitted via the existing
audit mechanism (charter decision 9).

Anti-oracle (R-S4): a key must be stored (encrypted) before validation; the
validate probe is capped at ≤5/10min and ≤10 distinct key fingerprints/day;
the probe's error is normalized/redacted (no vendor headers/request-ids/raw
body/key echo).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import (
    ByokCapabilityRevokedError,
    ByokCredentialNotFoundError,
    ByokModelNotAllowedError,
    ByokProviderNotAllowedError,
    ByokValidateRateLimitedError,
)
from app.core.logging import get_logger
from app.models.audit import AuditEvent
from app.models.user import User
from app.models.user_llm_credential import (
    VALIDATION_ERROR,
    VALIDATION_INVALID,
    VALIDATION_UNVALIDATED,
    VALIDATION_VALID,
    UserLLMCredential,
)
from app.repositories import audit as audit_repo
from app.repositories import user_llm_credentials as cred_repo
from app.services.byok import build_provider_from_spec
from app.services.byok import is_auth_error as byok_is_auth_error
from app.services.capabilities import can_use_byok
from app.services.llm import ChatMessage
from app.services.llm_providers import PROVIDER_REGISTRY, get_spec

log = get_logger(__name__)

# Anti-oracle caps (R-S4).
_VALIDATE_WINDOW = timedelta(minutes=10)
_VALIDATE_MAX_PER_WINDOW = 5
_DISTINCT_KEY_WINDOW = timedelta(days=1)
_DISTINCT_KEY_MAX_PER_DAY = 10

_AUDIT_CREATED = "byok.credential_created"
_AUDIT_UPDATED = "byok.credential_updated"
_AUDIT_DELETED = "byok.credential_deleted"
_AUDIT_VALIDATED = "byok.credential_validated"


def _require_capability(user: User) -> None:
    """can_use_byok gate + the feature flag. Raises 403 when closed."""
    if not get_settings().feature_byok_enabled or not can_use_byok(user):
        raise ByokCapabilityRevokedError(
            "BYOK is not available for your account.", details={"capability": "can_use_byok"}
        )


def _require_real_kek_for_store() -> None:
    """Refuse to store a real key under a derived dev KEK unless opted in.

    A derived KEK can't survive a restart, so a stored key would be
    unrecoverable. ``byok_allow_derived_kek=true`` is the dev-only escape.
    """
    secrets_crypto.reset_for_tests()  # re-resolve in case env flipped under us
    # ``active_kek_is_derived`` is exposed by the foundation crypto via the
    # internal cache; fall back to the prod_guards helper shape.
    try:
        from app.core.prod_guards import _has_real_kek

        real = _has_real_kek(get_settings())
    except Exception:  # pragma: no cover - defensive
        real = False
    if not real and not get_settings().byok_allow_derived_kek:
        raise ByokCapabilityRevokedError(
            "Storing a key requires a configured master key (KEK).",
            details={"reason": "derived_kek"},
        )


def _validate_provider_model(provider: str, model: str) -> None:
    if get_spec(provider) is None:
        raise ByokProviderNotAllowedError(
            "That provider is not supported.", details={"provider": provider}
        )
    if model not in PROVIDER_REGISTRY[provider].models:
        raise ByokModelNotAllowedError(
            "That model is not allowed for this provider.",
            details={"provider": provider, "model": model},
        )


async def upsert(
    db: AsyncSession,
    *,
    user: User,
    provider: str,
    model: str,
    api_key: str,
    allow_platform_fallback: bool = True,
) -> UserLLMCredential:
    """Create or update the user's credential for ``provider``.

    Idempotent on ``(provider, model, key_fingerprint)`` (FR-BYOK-08): the
    same payload twice yields one live row. Encrypts the key, stores
    fingerprint + last4, sets ``unvalidated``. Auto-validates ONCE on
    create. Emits the create/update audit event.
    """
    _require_capability(user)
    _validate_provider_model(provider, model)
    _require_real_kek_for_store()

    fingerprint = secrets_crypto.key_fingerprint(api_key)
    existing = await cred_repo.get_for_user_provider(db, user.id, provider)

    is_create = existing is None
    if existing is not None:
        idempotent = existing.model == model and existing.key_fingerprint == fingerprint
        existing.model = model
        existing.allow_platform_fallback = allow_platform_fallback
        if not idempotent:
            blob = secrets_crypto.encrypt(api_key.encode())
            existing.enc_blob = blob
            existing.key_version = get_settings().byok_master_key_version
            existing.key_fingerprint = fingerprint
            existing.last4 = secrets_crypto.last4(api_key)
            existing.last_validation_status = VALIDATION_UNVALIDATED
            existing.last_validated_at = None
        cred = existing
        await db.flush()
    else:
        blob = secrets_crypto.encrypt(api_key.encode())
        cred = UserLLMCredential(
            user_id=user.id,
            provider=provider,
            model=model,
            enc_blob=blob,
            key_version=get_settings().byok_master_key_version,
            key_fingerprint=fingerprint,
            last4=secrets_crypto.last4(api_key),
            allow_platform_fallback=allow_platform_fallback,
            enabled=True,
            is_active=False,
            last_validation_status=VALIDATION_UNVALIDATED,
        )
        db.add(cred)
        await db.flush()

    await audit_repo.record(
        db,
        actor_id=user.id,
        action=_AUDIT_CREATED if is_create else _AUDIT_UPDATED,
        target_type="user_llm_credential",
        target_id=cred.id,
        data={"provider": provider, "model": model},
    )

    # Auto-validate ONCE on create (no auto-revalidate loop). The probe
    # shares the manual-validate anti-oracle caps (Gate-A fix): when the
    # caps are exhausted the credential is still stored, just unvalidated —
    # the UI's manual validate (itself capped) picks it up later. Storage
    # is not the oracle; the probe is.
    if is_create:
        try:
            await _enforce_validation_caps(db, user.id)
        except ByokValidateRateLimitedError:
            log.info(
                "byok_auto_validate_skipped_capped",
                user_id=user.id,
                provider=provider,
            )
        else:
            await _run_validation(db, user=user, cred=cred, api_key=api_key, count_audit=True)

    return cred


async def patch(
    db: AsyncSession,
    *,
    user: User,
    provider: str,
    enabled: bool | None = None,
    is_active: bool | None = None,
    allow_platform_fallback: bool | None = None,
) -> UserLLMCredential:
    """Toggle flags. Setting active demotes any prior active (≤1)."""
    _require_capability(user)
    cred = await cred_repo.get_for_user_provider(db, user.id, provider)
    if cred is None:
        raise ByokCredentialNotFoundError("No credential for that provider.")

    if enabled is not None:
        cred.enabled = enabled
    if allow_platform_fallback is not None:
        cred.allow_platform_fallback = allow_platform_fallback
    if is_active is not None:
        if is_active:
            # Demote any other active credential first (≤1 active per user).
            prior = await cred_repo.get_active_for_user(db, user.id)
            if prior is not None and prior.id != cred.id:
                prior.is_active = False
                await db.flush()
        cred.is_active = is_active
    await db.flush()

    await audit_repo.record(
        db,
        actor_id=user.id,
        action=_AUDIT_UPDATED,
        target_type="user_llm_credential",
        target_id=cred.id,
        data={"provider": provider},
    )
    return cred


async def delete(db: AsyncSession, *, user: User, provider: str) -> None:
    """Soft-delete + clear active. Resolution falls back to platform."""
    _require_capability(user)
    cred = await cred_repo.get_for_user_provider(db, user.id, provider)
    if cred is None:
        raise ByokCredentialNotFoundError("No credential for that provider.")
    await cred_repo.soft_delete(db, cred)
    await audit_repo.record(
        db,
        actor_id=user.id,
        action=_AUDIT_DELETED,
        target_type="user_llm_credential",
        target_id=cred.id,
        data={"provider": provider},
    )


async def _count_recent_validations(db: AsyncSession, user_id: str) -> int:
    since = datetime.now(UTC) - _VALIDATE_WINDOW
    stmt = select(func.count(AuditEvent.id)).where(
        AuditEvent.actor_id == user_id,
        AuditEvent.action == _AUDIT_VALIDATED,
        AuditEvent.created_at >= since,
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _count_distinct_keys_today(db: AsyncSession, user_id: str) -> int:
    since = datetime.now(UTC) - _DISTINCT_KEY_WINDOW
    # Distinct fingerprints validated in the window, read from the audit
    # data->>'fingerprint' field.
    stmt = select(func.count(func.distinct(AuditEvent.data["fingerprint"].astext))).where(
        AuditEvent.actor_id == user_id,
        AuditEvent.action == _AUDIT_VALIDATED,
        AuditEvent.created_at >= since,
    )
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _enforce_validation_caps(db: AsyncSession, user_id: str) -> None:
    """Raise when the anti-oracle probe caps are exhausted (R-S4).

    ≤5 validations/10min and ≤10 distinct fingerprints/day, counted from
    the audit trail so manual validates and create-time auto-validates
    share one budget (Gate-A fix: the auto-validate path previously ran
    uncapped, so delete/recreate cycling gave unlimited free probes).
    """
    if await _count_recent_validations(db, user_id) >= _VALIDATE_MAX_PER_WINDOW:
        raise ByokValidateRateLimitedError(
            "Too many validation attempts. Try again later.",
            details={"window_minutes": 10},
        )
    if await _count_distinct_keys_today(db, user_id) >= _DISTINCT_KEY_MAX_PER_DAY:
        raise ByokValidateRateLimitedError(
            "Too many distinct keys validated today. Try again later.",
            details={"window": "day"},
        )


async def validate(db: AsyncSession, *, user: User, provider: str) -> tuple[str, str]:
    """Probe the stored key against the registry-fixed base (R-S4).

    Anti-oracle: the key must be stored first (handled by the repo lookup —
    no validate-without-store); ≤5 validations/10min and ≤10 distinct
    fingerprints/day. Returns ``(status, redacted_message)``.
    """
    _require_capability(user)
    cred = await cred_repo.get_for_user_provider(db, user.id, provider)
    if cred is None:
        # No stored credential → cannot validate (must store before validate).
        raise ByokCredentialNotFoundError("No credential to validate for that provider.")

    await _enforce_validation_caps(db, user.id)

    api_key = secrets_crypto.decrypt(cred.enc_blob).decode("utf-8")
    return await _run_validation(db, user=user, cred=cred, api_key=api_key, count_audit=True)


async def _run_validation(
    db: AsyncSession,
    *,
    user: User,
    cred: UserLLMCredential,
    api_key: str,
    count_audit: bool,
) -> tuple[str, str]:
    """Run the cheapest auth probe against the registry-fixed base.

    Errors are NORMALIZED + REDACTED — we never echo the vendor's raw error,
    request-id, headers, or the key. The audit event records status only.
    """
    spec = get_spec(cred.provider)
    status = VALIDATION_ERROR
    message = "Could not validate the key."
    if spec is not None and cred.model in spec.models:
        provider_obj = build_provider_from_spec(spec, api_key=api_key, model=cred.model)
        try:
            await provider_obj.chat_with_usage(
                [ChatMessage(role="user", content="ping")], temperature=0.0
            )
            status = VALIDATION_VALID
            message = "Valid"
        except Exception as exc:
            # Normalize: classify auth-ish failures as invalid; everything
            # else as a transient error. NEVER surface the raw exception
            # text. Shares byok.is_auth_error so validation and dispatch
            # (ADR-0027 §4 item 3) classify identically.
            if byok_is_auth_error(exc):
                status = VALIDATION_INVALID
                message = "Invalid key"
            else:
                status = VALIDATION_ERROR
                message = "Could not validate the key."
            log.info(
                "byok_validate_probe_failed", provider=cred.provider, error_kind=type(exc).__name__
            )
    else:
        status = VALIDATION_ERROR
        message = "That model is no longer available."

    cred.last_validation_status = status
    cred.last_validated_at = datetime.now(UTC)
    await db.flush()

    if count_audit:
        await audit_repo.record(
            db,
            actor_id=user.id,
            action=_AUDIT_VALIDATED,
            target_type="user_llm_credential",
            target_id=cred.id,
            # fingerprint powers the distinct-key anti-oracle cap; it is a
            # SHA-256 hash, not the key.
            data={"provider": cred.provider, "status": status, "fingerprint": cred.key_fingerprint},
        )
    return status, message


async def rotate_master_key(db: AsyncSession, *, batch_size: int = 200) -> tuple[int, int]:
    """Re-wrap every credential's DEK under the active KEK version (FR-BYOK-12).

    R-S2 operational procedure. Uses ``secrets_crypto.rotate_secret`` which
    re-wraps the ``enc_data_key`` ONLY — the inner ``enc_key`` (the encrypted
    plaintext) is preserved byte-for-byte, so the plaintext key is never
    touched or surfaced. Updates ``key_version`` to the active version. Emits
    a single ``byok.master_key_rotated`` audit event (counts only). Returns
    ``(rotated, skipped)``.

    Precondition (R-S2): the target version KEK must be present in
    ``byok_master_keys`` (all versions deployed fleet-wide before rotation)
    and old versions retained until rotation completes — this is enforced by
    ``secrets_crypto`` raising if a version is missing, and documented in the
    runbook.
    """
    active_version = get_settings().byok_master_key_version
    rotated = 0
    skipped = 0
    offset = 0
    while True:
        rows = (
            (
                await db.execute(
                    select(UserLLMCredential)
                    .order_by(UserLLMCredential.id)
                    .offset(offset)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            break
        for cred in rows:
            if cred.key_version == active_version:
                skipped += 1
                continue
            # rotate_secret re-wraps enc_data_key under the active KEK; the
            # inner enc_key (encrypted plaintext) is untouched.
            cred.enc_blob = secrets_crypto.rotate_secret(cred.enc_blob)
            cred.key_version = active_version
            rotated += 1
        await db.flush()
        await db.commit()
        offset += batch_size

    await audit_repo.record(
        db,
        actor_id=None,
        action="byok.master_key_rotated",
        target_type="user_llm_credential",
        target_id=None,
        data={"rotated": rotated, "skipped": skipped, "to_version": active_version},
    )
    await db.commit()
    return rotated, skipped


__all__ = ["delete", "patch", "rotate_master_key", "upsert", "validate"]
