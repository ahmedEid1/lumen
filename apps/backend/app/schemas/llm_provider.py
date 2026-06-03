"""Public DTOs for the allowlisted provider registry — ADR-0027 §API (S5.2).

The wire shape exposes only ``provider``, ``display_name`` and ``models``.
The registry's ``base_url`` is server-internal (the SSRF lockdown surface,
DR-17) and MUST NOT appear in any DTO; there is likewise no key material
anywhere in this module.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProviderInfo(BaseModel):
    """One allowlisted provider, as seen by the client."""

    provider: str
    display_name: str
    models: list[str]


class ProviderRegistryOut(BaseModel):
    """The full read-only registry response."""

    providers: list[ProviderInfo]


__all__ = ["ProviderInfo", "ProviderRegistryOut"]
