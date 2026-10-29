"""L01: Groq reasoning models (openai/gpt-oss-*, qwen/*) get their own output-limit
parameters; every other provider keeps sending exactly ``max_tokens``.

Groq-only parameters (reasoning_effort, include_reasoning, reasoning_format) are
rejected by OpenAI and Mistral, so the gate is the exact Groq host.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.core.config import get_settings
from app.services.llm import (
    ChatMessage,
    OpenAIProvider,
    completion_limit_kwargs,
    is_groq_reasoning_model,
)

GROQ = "https://api.groq.com/openai/v1"


@pytest.mark.parametrize(
    ("base", "model"),
    [
        ("https://api.openai.com/v1", "gpt-4o-mini"),
        ("https://api.mistral.ai/v1", "mistral-small-latest"),
        (None, "openai/gpt-oss-120b"),
        (GROQ, "llama-3.3-70b-versatile"),
        ("https://api.groq.com.evil.example/openai/v1", "openai/gpt-oss-120b"),
        ("https://evil.example/api.groq.com", "openai/gpt-oss-120b"),
    ],
)
def test_non_groq_or_non_reasoning_models_send_only_max_tokens(
    base: str | None, model: str
) -> None:
    assert not is_groq_reasoning_model(base, model)
    assert completion_limit_kwargs(base, model, 4096) == {"max_tokens": 4096}


def test_groq_gpt_oss_caps_reasoning_and_hides_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_REASONING_EFFORT", "medium")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        kw = completion_limit_kwargs(GROQ, "openai/gpt-oss-120b", 4096)
    finally:
        get_settings.cache_clear()  # type: ignore[attr-defined]
    assert kw == {
        "max_completion_tokens": 4096,
        "reasoning_effort": "medium",
        "extra_body": {"include_reasoning": False},
    }
    assert "max_tokens" not in kw


def test_groq_gpt_oss_defaults_to_low_effort() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]
    assert completion_limit_kwargs(GROQ, "openai/gpt-oss-20b", 2048)["reasoning_effort"] == "low"


def test_groq_qwen_hides_think_tags_without_effort() -> None:
    kw = completion_limit_kwargs(GROQ, "qwen/qwen3.8-27b", 2048)
    assert kw == {"max_completion_tokens": 2048, "extra_body": {"reasoning_format": "hidden"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base", "model", "expect_key", "absent_key"),
    [
        (GROQ, "openai/gpt-oss-120b", "max_completion_tokens", "max_tokens"),
        ("https://api.openai.com/v1", "gpt-4o-mini", "max_tokens", "reasoning_effort"),
    ],
)
async def test_openai_provider_sends_the_gated_kwargs_and_reports_finish_reason(
    monkeypatch: pytest.MonkeyPatch, base: str, model: str, expect_key: str, absent_key: str
) -> None:
    captured: dict = {}

    class _Msg:
        content = "partial"

    class _Choice:
        message = _Msg()
        finish_reason = "length"

    class _Usage:
        prompt_tokens = 11
        completion_tokens = 4096

    class _Completion:
        choices = [_Choice()]  # noqa: RUF012 — test stub
        usage = _Usage()

    class _FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self._create)
            )

        def _create(self, **kwargs: object) -> _Completion:
            captured.update(kwargs)
            return _Completion()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))
    provider = OpenAIProvider(api_key="k", model=model, api_base=base, max_tokens=4096)
    resp = await provider.chat_with_usage([ChatMessage(role="user", content="hi")])

    assert captured[expect_key] == 4096
    assert absent_key not in captured
    assert resp.finish_reason == "length"
    assert resp.completion_tokens == 4096


def test_streamed_turns_are_priced_from_the_shared_table() -> None:
    # The stream path used to import a non-existent ``cost_for`` and meter every
    # streamed tutor turn at $0, so the daily budget guard never saw them.
    from app.services.llm_stream import _estimate_cost

    assert _estimate_cost("openai/gpt-oss-120b", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert _estimate_cost("openai/gpt-oss-20b", 1_000_000, 0) == pytest.approx(0.075)
    assert _estimate_cost("unpriced/model", 10, 10) == 0.0
