"""Allowlisted BYOK provider registry — ADR-0027 §1 (S5.2).

A **frozen, in-code** registry of the providers a user may bring a key
for. The base URL is *never* user-supplied — it lives here, server-owned,
which closes the SSRF/exfil surface the charter (decision 5, FR-BYOK-14)
calls out: a BYOK credential can only ever talk to one of these fixed
endpoints.

Why a code constant and not a DB table (R-G4): the model allowlist is a
curated, versioned artifact maintained with the app. There is no admin
CRUD surface in v1 — a model-curation change is a deploy, not a live edit,
which keeps the attack surface (and the audit story) minimal. Revisit with
a DB-backed registry ADR if churn grows.

The registry is exposed read-only via ``GET /api/v1/llm-providers`` so the
frontend never hard-codes the provider/model list (FR-BYOK-20). That public
shape exposes ``provider``, ``display_name`` and ``models`` only — never the
``base_url`` (the SSRF lockdown surface) or any key field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Transport = Literal["openai", "anthropic"]
ValidateStrategy = Literal["chat_min", "models_list"]


@dataclass(frozen=True)
class ProviderSpec:
    """One allowlisted provider. Frozen — mutating raises ``FrozenInstanceError``.

    ``base_url`` is server-owned and FIXED; it is the only place a BYOK
    request's endpoint comes from (DR-17). ``transport`` selects which
    concrete provider class in ``app.services.llm`` speaks the wire shape.
    ``models`` is the curated allowlist (R-G4) — a stored credential whose
    model drifts out of this tuple triggers the R-M11' drift handling.
    """

    key: str
    display_name: str
    base_url: str
    transport: Transport
    models: tuple[str, ...]
    key_min_len: int = 20
    key_max_len: int = 512
    validate_strategy: ValidateStrategy = "chat_min"


# The frozen registry. Keys are the on-the-wire provider slugs. ``groq`` is
# a first-class entry (FR-BYOK-13) carrying llama-3.3-70b-versatile, the
# free-tier default the platform itself runs on.
PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        key="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        transport="openai",
        models=("gpt-4o-mini", "gpt-4o"),
    ),
    "anthropic": ProviderSpec(
        key="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com",
        transport="anthropic",
        models=("claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
    ),
    "groq": ProviderSpec(
        key="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        transport="openai",
        models=("llama-3.3-70b-versatile",),
    ),
    "mistral": ProviderSpec(
        key="mistral",
        display_name="Mistral",
        base_url="https://api.mistral.ai/v1",
        transport="openai",
        models=("mistral-small-latest",),
    ),
}


def get_spec(provider: str) -> ProviderSpec | None:
    """Return the spec for ``provider`` or ``None`` if not allowlisted."""
    return PROVIDER_REGISTRY.get(provider)


def is_allowed_model(provider: str, model: str) -> bool:
    """True iff ``model`` is in the curated allowlist for ``provider``."""
    spec = PROVIDER_REGISTRY.get(provider)
    return spec is not None and model in spec.models


__all__ = [
    "PROVIDER_REGISTRY",
    "ProviderSpec",
    "Transport",
    "ValidateStrategy",
    "get_spec",
    "is_allowed_model",
]
