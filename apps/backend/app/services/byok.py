"""BYOK dispatch — initiation-locus resolution + decrypt-at-dispatch-only.

ADR-0027 §4 (S5.7), DR-8/DR-17/R-M11'/R-S1''. This module is the single
home for two things:

1. **resolve_context** (API-side, no decrypt): pick the acting user's
   active/enabled/not-invalid credential id and stamp it onto an
   ``LLMContext``. The context is what gets threaded through every
   user-initiated foreground call site and (as ``credential_id``) carried
   in Celery payloads.

2. **build_provider** (THE ONLY DECRYPT SITE): given a context, decrypt the
   key exactly once and return ``(provider, billing_mode)``. Applies the
   model-allowlist drift rule (R-M11'), the platform-fallback consent, and
   the R-S1'' "background ctx → platform always" rule.

The locus is decided by the **initiator**, not the execution venue: the
same ``replan_for_user`` is BYOK from the API handler and platform from the
monthly beat, because the caller passes the right context (R-S1''). Every
call site defaults ``ctx=PLATFORM_CONTEXT`` so partial threading never
regresses behavior.

No process-wide or Redis cache of decrypted keys (FR-BYOK-25) — the
returned provider object is request-scoped and dropped at request end.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secrets_crypto
from app.core.config import get_settings
from app.core.errors import ByokModelUnavailableError, ByokProviderError
from app.core.logging import get_logger
from app.models.llm_call import BILLING_BYOK, BILLING_PLATFORM, SYSTEM_USER_ID
from app.models.user_llm_credential import (
    VALIDATION_INVALID,
    VALIDATION_NEEDS_ATTENTION,
    UserLLMCredential,
)
from app.repositories import user_llm_credentials as cred_repo
from app.services.llm import LLMProvider, build_provider_from_spec, get_provider
from app.services.llm_providers import get_spec

log = get_logger(__name__)

# URL-ish field names that must never appear on a credential payload — a
# stored base URL is the SSRF vector BYOK structurally forbids (DR-17,
# FR-BYOK-14). Checked in the schema validator (S5.9) via this helper.
_URLISH_FIELDS = frozenset({"base_url", "api_base", "host", "url", "endpoint", "base"})


@dataclass(frozen=True)
class LLMContext:
    """The initiation context that decides BYOK vs platform (ADR-0027 §4).

    Threaded from the *initiator*. ``foreground=True`` marks a user-initiated
    call (BYOK-eligible); a background/beat/system call uses
    ``PLATFORM_CONTEXT`` (or ``foreground=False``) and is platform always.
    ``credential_id`` is set by ``resolve_context`` (foreground) and carried
    verbatim in Celery payloads — never the key.
    """

    user_id: str | None
    credential_id: str | None = None
    foreground: bool = False
    mode: str = "platform"  # "platform" | "byok" — informational; build_provider re-derives


PLATFORM_CONTEXT = LLMContext(
    user_id=SYSTEM_USER_ID, credential_id=None, foreground=False, mode="platform"
)


def base_url_forbidden(field_names) -> str | None:
    """Return the first URL-ish field name present, or ``None`` (FR-BYOK-14)."""
    for name in field_names:
        if name.lower() in _URLISH_FIELDS:
            return name
    return None


def _byok_enabled() -> bool:
    return bool(getattr(get_settings(), "feature_byok_enabled", False))


async def resolve_context(db: AsyncSession, *, user_id: str | None) -> LLMContext:
    """Resolve the foreground BYOK context for ``user_id`` (NO decrypt).

    Returns a foreground ``LLMContext`` carrying the user's active credential
    id when one is usable; otherwise a foreground platform context. Picks the
    credential by repo (active + enabled + live); does not decrypt — that is
    ``build_provider``'s job and the decrypt-locus spy test pins it.

    When the feature flag is off, or there's no user / a system user, the
    result resolves to platform.
    """
    if not user_id or user_id == SYSTEM_USER_ID or not _byok_enabled():
        return LLMContext(user_id=user_id, credential_id=None, foreground=True, mode="platform")

    cred = await cred_repo.get_active_for_user(db, user_id)
    if cred is None or not cred.enabled or cred.last_validation_status == VALIDATION_INVALID:
        return LLMContext(user_id=user_id, credential_id=None, foreground=True, mode="platform")

    return LLMContext(user_id=user_id, credential_id=cred.id, foreground=True, mode="byok")


async def build_provider(db: AsyncSession, ctx: LLMContext) -> tuple[LLMProvider, str]:
    """Return ``(provider, billing_mode)`` for a context — THE ONLY DECRYPT SITE.

    Precedence (ADR-0027 §4):

    * Background ctx (``foreground=False``) → platform always (R-S1'').
    * No credential id / flag off → platform.
    * Credential present:
        - model drifted out of the allowlist (R-M11'):
            * ``allow_platform_fallback`` → platform + mark
              ``needs_attention`` + log the notice;
            * else hard-fail ``tutor.byok_provider_error``.
        - otherwise decrypt the key once and build the registry-fixed
          provider with the user's model → billing_mode="byok".
    """
    if not ctx.foreground or not ctx.credential_id or not _byok_enabled():
        return get_provider(), BILLING_PLATFORM

    cred = await cred_repo.get_by_id(db, ctx.credential_id)
    if (
        cred is None
        or not cred.enabled
        or cred.is_active is False
        or cred.last_validation_status == VALIDATION_INVALID
    ):
        # The credential vanished / was disabled / went invalid between
        # resolve and dispatch → platform (no decrypt).
        return get_provider(), BILLING_PLATFORM

    spec = get_spec(cred.provider)
    if spec is None:
        # Provider itself dropped out of the registry — treat as drift.
        return await _handle_drift(db, cred)

    if cred.model not in spec.models:
        return await _handle_drift(db, cred)

    # --- The single decrypt. Plaintext lives only in this local + the
    # request-scoped provider object that wraps it in SecretStr. ---
    plaintext = secrets_crypto.decrypt(cred.enc_blob).decode("utf-8")
    provider = build_provider_from_spec(spec, api_key=plaintext, model=cred.model)
    return provider, BILLING_BYOK


async def _handle_drift(db: AsyncSession, cred: UserLLMCredential) -> tuple[LLMProvider, str]:
    """Model-allowlist drift (R-M11'). Fall back to platform with consent,
    else hard-fail. Never silently dispatch a disallowed model."""
    if cred.allow_platform_fallback:
        if cred.last_validation_status != VALIDATION_NEEDS_ATTENTION:
            cred.last_validation_status = VALIDATION_NEEDS_ATTENTION
            await db.flush()
        # One-time notice surfaced via logs; the API/UI reads
        # last_validation_status="needs_attention" + the NeedsAttentionBanner.
        log.info(
            "byok_model_unavailable_fallback",
            credential_id=cred.id,
            provider=cred.provider,
        )
        return get_provider(), BILLING_PLATFORM
    raise ByokModelUnavailableError(
        "The selected model is no longer available.",
        details={"provider": cred.provider},
    )


async def stream_dispatch_for_turn(
    db: AsyncSession, *, credential_id: str | None, user_id: str
) -> dict[str, str] | None:
    """Resolve a streaming BYOK dispatch dict for a worker turn (S5.12).

    The streaming tutor runs in a Celery worker; the turn row carries the
    foreground-resolved ``credential_id`` (never the key — FR-BYOK-26). Here,
    inside the worker trust boundary, we rebuild the foreground ctx and run
    ``build_provider`` (the only decrypt site) to get the per-request key,
    then return ``{transport, base_url, api_key, model}`` for
    ``stream_chat(byok_dispatch=...)``. Returns ``None`` for the platform path
    (no credential / flag off / drift fallback) so the streamer uses the
    global provider switch unchanged.
    """
    if not credential_id or not _byok_enabled():
        return None
    ctx = LLMContext(user_id=user_id, credential_id=credential_id, foreground=True, mode="byok")
    provider, mode = await build_provider(db, ctx)
    if mode != BILLING_BYOK:
        return None
    # ``provider`` is a SecretStr-wrapped registry provider; pull the
    # per-request key + base from it for the streaming client.
    return {
        "transport": "anthropic" if type(provider).__name__ == "AnthropicProvider" else "openai",
        "base_url": getattr(provider, "_api_base", "") or "",
        "api_key": provider._key_value(),  # type: ignore[attr-defined]
        "model": getattr(provider, "_model", ""),
    }


def redact_provider_error(exc: BaseException) -> ByokProviderError:
    """Wrap a provider dispatch failure in a redacted, fallback-free error.

    Used by call sites that catch a BYOK dispatch exception when
    ``allow_platform_fallback=False``. The message is generic — no vendor
    headers, request-ids, raw bodies, or key echo (ADR-0027 §4 item 3).
    """
    return ByokProviderError("Your provider rejected the request. Check your key.")


__all__ = [
    "PLATFORM_CONTEXT",
    "LLMContext",
    "base_url_forbidden",
    "build_provider",
    "redact_provider_error",
    "resolve_context",
    "stream_dispatch_for_turn",
]
