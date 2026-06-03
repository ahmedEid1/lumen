"""S5.2 — allowlisted provider registry + GET /llm-providers.

The registry unit tests are pure (no DB / no app) and run anywhere. The
API tests use the ``client``/``auth_headers`` fixtures and run against the
real Postgres stack at ``make test.api``.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.models.user import Role
from app.services.llm_providers import PROVIDER_REGISTRY, ProviderSpec, is_allowed_model

# ---------------------------------------------------------------------------
# Registry unit tests (pure — no fixtures)
# ---------------------------------------------------------------------------


def test_groq_present_with_fixed_base_url_and_model() -> None:
    spec = PROVIDER_REGISTRY["groq"]
    assert spec.base_url == "https://api.groq.com/openai/v1"
    assert "llama-3.3-70b-versatile" in spec.models


def test_every_spec_is_well_formed() -> None:
    assert PROVIDER_REGISTRY, "registry must not be empty"
    for key, spec in PROVIDER_REGISTRY.items():
        assert spec.key == key
        assert spec.base_url.startswith("https://"), f"{key} base_url must be https"
        assert spec.base_url, f"{key} base_url must be non-empty"
        assert isinstance(spec.models, tuple) and spec.models, f"{key} needs models"
        assert spec.transport in {"openai", "anthropic"}
        assert spec.display_name


def test_registry_specs_are_frozen() -> None:
    spec = PROVIDER_REGISTRY["openai"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.base_url = "https://evil.example"  # type: ignore[misc]


def test_is_allowed_model() -> None:
    assert is_allowed_model("openai", "gpt-4o-mini")
    assert not is_allowed_model("openai", "gpt-4o-mini-not-real")
    assert not is_allowed_model("nonexistent", "anything")


def test_spec_defaults() -> None:
    spec = ProviderSpec(
        key="x", display_name="X", base_url="https://x", transport="openai", models=("m",)
    )
    assert spec.key_min_len == 20
    assert spec.key_max_len == 512
    assert spec.validate_strategy == "chat_min"


# ---------------------------------------------------------------------------
# API tests (DB-backed — run at make test.api)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_providers_endpoint_shape(client, auth_headers) -> None:
    headers = await auth_headers(role=Role.student)
    resp = await client.get("/api/v1/llm-providers", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "providers" in body
    by_key = {p["provider"]: p for p in body["providers"]}
    assert "groq" in by_key
    groq = by_key["groq"]
    # Public shape: provider/display_name/models ONLY.
    assert set(groq.keys()) == {"provider", "display_name", "models"}
    assert "llama-3.3-70b-versatile" in groq["models"]
    # The SSRF lockdown surface (base_url) and any key field MUST be absent.
    for prov in body["providers"]:
        assert "base_url" not in prov
        assert "api_key" not in prov
        assert "key" not in prov


@pytest.mark.asyncio
async def test_llm_providers_requires_auth(client) -> None:
    resp = await client.get("/api/v1/llm-providers")
    assert resp.status_code == 401
