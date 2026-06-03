"""S5.6 — provider key safety: SecretStr wrap + redacting repr/str.

Pure-unit (no DB / no network). The SDK is never imported: we assert the
key never appears in ``repr()``/``str()`` and that the real key reaches the
SDK constructor (mocked), and that ``build_provider_from_spec`` has no
``api_base`` parameter (DR-17 — base_url comes only from the registry).
"""

from __future__ import annotations

import inspect

import pytest

from app.services.llm import (
    AnthropicProvider,
    MistralProvider,
    OpenAIProvider,
    build_provider_from_spec,
    get_provider,
)
from app.services.llm_providers import PROVIDER_REGISTRY

SENTINEL = "sk-SENTINEL-1234567890abcdef"


@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider, MistralProvider])
def test_repr_and_str_never_contain_the_key(cls) -> None:
    provider = cls(api_key=SENTINEL, model="some-model")
    assert "SENTINEL" not in repr(provider)
    assert "SENTINEL" not in str(provider)
    # The model is fine to show (it is not a secret) and is useful for logs.
    assert "some-model" in repr(provider)


@pytest.mark.parametrize("cls", [OpenAIProvider, AnthropicProvider])
def test_real_key_reaches_the_sdk(cls, monkeypatch) -> None:
    """The decrypted key must still flow into the vendor SDK constructor."""
    captured: dict[str, object] = {}

    provider = cls(api_key=SENTINEL, model="some-model")

    # Patch the SDK import target inside ``_get_client`` by intercepting the
    # constructor each provider calls. Both providers stash kwargs into a
    # client; we replace the client class via the module that _get_client
    # imports lazily.
    if cls is OpenAIProvider:
        import sys
        import types

        fake = types.ModuleType("openai")

        def _OpenAI(**kwargs):
            captured.update(kwargs)
            return object()

        fake.OpenAI = _OpenAI
        monkeypatch.setitem(sys.modules, "openai", fake)
    else:
        import sys
        import types

        fake = types.ModuleType("anthropic")

        def _Anthropic(**kwargs):
            captured.update(kwargs)
            return object()

        fake.Anthropic = _Anthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake)

    provider._get_client()
    assert captured["api_key"] == SENTINEL


def test_build_provider_from_spec_has_no_api_base_param() -> None:
    """DR-17: no caller can inject a custom base URL on the BYOK path."""
    sig = inspect.signature(build_provider_from_spec)
    assert "api_base" not in sig.parameters
    assert "base_url" not in sig.parameters


def test_build_provider_from_spec_uses_registry_base() -> None:
    spec = PROVIDER_REGISTRY["groq"]
    provider = build_provider_from_spec(spec, api_key=SENTINEL, model="llama-3.3-70b-versatile")
    # groq uses the openai transport; the base must be the registry-fixed one.
    assert isinstance(provider, OpenAIProvider)
    assert provider._api_base == spec.base_url
    assert provider._model == "llama-3.3-70b-versatile"
    # key still redacted in repr
    assert "SENTINEL" not in repr(provider)

    anth_spec = PROVIDER_REGISTRY["anthropic"]
    anth = build_provider_from_spec(anth_spec, api_key=SENTINEL, model="claude-haiku-4-5-20251001")
    assert isinstance(anth, AnthropicProvider)
    assert anth._api_base == anth_spec.base_url


def test_get_provider_stays_zero_arg() -> None:
    """System/eval path keeps working unchanged (no required args)."""
    sig = inspect.signature(get_provider)
    assert all(
        p.default is not inspect.Parameter.empty or p.kind == p.VAR_KEYWORD
        for p in sig.parameters.values()
    )


def test_empty_key_guard_uses_secret_value() -> None:
    """SecretStr('') is truthy, so the unset-key guard must check the value."""
    provider = OpenAIProvider(api_key="", model="m")
    # The provider's unset-key guard should treat "" as unset.
    assert provider._key_value() == ""
