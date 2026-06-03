"""GET /api/v1/llm-providers — read-only allowlisted provider registry (S5.2).

Authenticated (anonymous → 401, FR-BYOK-22). Returns the curated provider +
model lists so the frontend never hard-codes them (FR-BYOK-20). The
server-owned ``base_url`` and any key material are deliberately absent from
the response shape.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.llm_provider import ProviderInfo, ProviderRegistryOut
from app.services.llm_providers import PROVIDER_REGISTRY

router = APIRouter()


@router.get("/llm-providers", response_model=ProviderRegistryOut)
async def list_llm_providers(_: CurrentUser) -> ProviderRegistryOut:
    """List allowlisted providers + their curated models.

    Requires authentication. Exposes ``provider``/``display_name``/``models``
    only — never ``base_url`` or any secret.
    """
    return ProviderRegistryOut(
        providers=[
            ProviderInfo(
                provider=spec.key,
                display_name=spec.display_name,
                models=list(spec.models),
            )
            for spec in PROVIDER_REGISTRY.values()
        ]
    )
