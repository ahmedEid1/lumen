"""BYOK credential DTOs — write-only key, masked reads (S5.9 / ADR-0027 §API).

The upsert payload accepts a ``SecretStr`` ``api_key`` (write-only) and
rejects any URL-ish field (``base_url|api_base|host|url|...``) with
``byok.base_url_forbidden`` — the base URL comes only from the registry
(DR-17, FR-BYOK-14). The public read DTO carries masked metadata only:
``last4`` + status, never the key / ``enc_*`` / ``key_version``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from app.core.errors import ByokBaseUrlForbiddenError
from app.services.byok import base_url_forbidden


class LLMCredentialUpsert(BaseModel):
    """Create/update a credential for a provider.

    ``model_config`` forbids extras so an unexpected URL-ish field is a hard
    422 rather than a silently-ignored input. The explicit validator gives
    the precise ``byok.base_url_forbidden`` code FR-BYOK-14 requires (a
    plain "extra forbidden" error wouldn't carry it).
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    api_key: SecretStr
    allow_platform_fallback: bool = True

    @model_validator(mode="before")
    @classmethod
    def _reject_urlish(cls, data):
        if isinstance(data, dict):
            offending = base_url_forbidden(data.keys())
            if offending is not None:
                raise ByokBaseUrlForbiddenError(
                    "A custom base URL or host is not allowed.",
                    details={"field": offending},
                )
        return data


class LLMCredentialPatch(BaseModel):
    """Toggle flags. All optional; only provided fields change."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    is_active: bool | None = None
    allow_platform_fallback: bool | None = None


class LLMCredentialPublic(BaseModel):
    """Masked read DTO — NEVER carries key material (FR-BYOK-17)."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    model: str
    last4: str
    enabled: bool
    is_active: bool
    allow_platform_fallback: bool
    last_validated_at: datetime | None
    last_validation_status: str
    created_at: datetime


class LLMCredentialValidateOut(BaseModel):
    """Redacted validate result — no vendor headers/request-ids/body/key."""

    status: str
    message: str


__all__ = [
    "LLMCredentialPatch",
    "LLMCredentialPublic",
    "LLMCredentialUpsert",
    "LLMCredentialValidateOut",
]
