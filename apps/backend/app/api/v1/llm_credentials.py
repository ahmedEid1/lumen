"""BYOK credential CRUD + validate — /api/v1/me/llm-credentials (S5.9).

Authenticated (anon → 401). Every endpoint re-checks ``can_use_byok`` in the
service layer (R-CAP). Reads are masked (no key material ever). slowapi
rate-limits the write/validate paths (FR-QUOTA-04). All under ``/me`` so the
acting user is always the resource owner.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser, DBSession
from app.core.ratelimit import limiter
from app.repositories import user_llm_credentials as cred_repo
from app.schemas.common import OkResponse
from app.schemas.llm_credential import (
    LLMCredentialPatch,
    LLMCredentialPublic,
    LLMCredentialUpsert,
    LLMCredentialValidateOut,
)
from app.services import llm_credentials as svc

router = APIRouter()


@router.get("/me/llm-credentials", response_model=list[LLMCredentialPublic])
async def list_my_credentials(user: CurrentUser, db: DBSession) -> list[LLMCredentialPublic]:
    """List the user's live credentials — masked metadata only."""
    rows = await cred_repo.list_for_user(db, user.id)
    return [LLMCredentialPublic.model_validate(r) for r in rows]


@router.put("/me/llm-credentials/{provider}", response_model=LLMCredentialPublic)
@limiter.limit("10/minute")
async def upsert_credential(
    provider: str,
    payload: LLMCredentialUpsert,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LLMCredentialPublic:
    """Create/update a credential for ``provider``. Write-only key."""
    cred = await svc.upsert(
        db,
        user=user,
        provider=provider,
        model=payload.model,
        api_key=payload.api_key.get_secret_value(),
        allow_platform_fallback=payload.allow_platform_fallback,
    )
    return LLMCredentialPublic.model_validate(cred)


@router.patch("/me/llm-credentials/{provider}", response_model=LLMCredentialPublic)
@limiter.limit("20/minute")
async def patch_credential(
    provider: str,
    payload: LLMCredentialPatch,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LLMCredentialPublic:
    """Toggle enabled / active / allow_platform_fallback."""
    cred = await svc.patch(
        db,
        user=user,
        provider=provider,
        enabled=payload.enabled,
        is_active=payload.is_active,
        allow_platform_fallback=payload.allow_platform_fallback,
    )
    return LLMCredentialPublic.model_validate(cred)


@router.delete("/me/llm-credentials/{provider}", response_model=OkResponse)
async def delete_credential(provider: str, user: CurrentUser, db: DBSession) -> OkResponse:
    """Soft-delete + clear active. Resolution falls back to platform."""
    await svc.delete(db, user=user, provider=provider)
    return OkResponse()


@router.post("/me/llm-credentials/{provider}/validate", response_model=LLMCredentialValidateOut)
@limiter.limit("10/minute")
async def validate_credential(
    provider: str,
    user: CurrentUser,
    db: DBSession,
    request: Request,
    response: Response,
) -> LLMCredentialValidateOut:
    """Probe the stored key (anti-oracle caps) — redacted result."""
    status, message = await svc.validate(db, user=user, provider=provider)
    return LLMCredentialValidateOut(status=status, message=message)
