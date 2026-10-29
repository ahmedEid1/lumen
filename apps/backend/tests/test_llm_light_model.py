"""L77: short authoring passes (quizzes, critic scorecards) can run on a smaller
model with its own provider rate budget; everything else stays on LLM_MODEL."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services import ai_authoring
from app.services import authoring_orchestrator as orch
from app.services.llm import (
    LIGHT_FEATURES,
    FallbackProvider,
    OpenAIProvider,
    get_provider,
    get_provider_for,
)


@pytest.fixture
def groq_with_light():
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "openai"),
        patch.object(s, "llm_model", "openai/gpt-oss-120b"),
        patch.object(s, "openai_api_key", SecretStr("sk-test")),
        patch.object(s, "openai_api_base", "https://api.groq.com/openai/v1"),
        patch.object(s, "llm_fallback_models", ["openai/gpt-oss-20b"]),
        patch.object(s, "llm_light_model", "openai/gpt-oss-20b"),
    ):
        yield


def _models(provider) -> list[str]:
    if isinstance(provider, FallbackProvider):
        return [p._model for p in provider._providers]
    return [provider._model]


def test_light_features_are_exactly_the_quiz_and_critic_passes() -> None:
    assert {"authoring.quiz", orch.FEATURE_CRITIC, orch.FEATURE_FINAL_CRITIC} == LIGHT_FEATURES
    for heavy in (
        "authoring.lesson",
        "authoring.outline",
        orch.FEATURE_OUTLINER,
        orch.FEATURE_REVISER,
    ):
        assert heavy not in LIGHT_FEATURES


@pytest.mark.parametrize("feature", sorted(LIGHT_FEATURES))
def test_light_features_run_on_the_light_model_first(groq_with_light, feature: str) -> None:
    assert _models(get_provider_for(feature)) == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]


@pytest.mark.parametrize(
    "feature", ["authoring.lesson", "authoring.outline", orch.FEATURE_REVISER, None, "tutor.synth"]
)
def test_everything_else_keeps_the_primary_chain(groq_with_light, feature: str | None) -> None:
    assert _models(get_provider_for(feature)) == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert _models(get_provider()) == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_without_a_light_model_nothing_is_routed(groq_with_light) -> None:
    with patch.object(get_settings(), "llm_light_model", ""):
        assert _models(get_provider_for("authoring.quiz")) == [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
        ]


def test_light_model_without_fallbacks_is_a_bare_provider(groq_with_light) -> None:
    with patch.object(get_settings(), "llm_fallback_models", []):
        quiz = get_provider_for("authoring.quiz")
        assert isinstance(quiz, FallbackProvider)  # light model, then the primary behind it
        assert _models(quiz) == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
        lesson = get_provider_for("authoring.lesson")
        assert isinstance(lesson, OpenAIProvider) and lesson._model == "openai/gpt-oss-120b"


def test_noop_is_never_routed() -> None:
    s = get_settings()
    with (
        patch.object(s, "llm_provider", "noop"),
        patch.object(s, "llm_light_model", "openai/gpt-oss-20b"),
    ):
        assert get_provider_for("authoring.quiz").name == "noop"


def test_quiz_feature_name_matches_the_routed_set() -> None:
    # generate_quiz meters (and is routed) under this name; keep them in step.
    import inspect

    assert 'feature="authoring.quiz"' in inspect.getsource(ai_authoring.generate_quiz)


class _Err(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(str(status))
        self.status_code = status


class _Fake:
    def __init__(self, model: str, outcome) -> None:
        self._model = model
        self.name = "openai"
        self._outcome = outcome
        self.calls = 0

    async def chat_with_usage(self, messages, temperature=0.2):
        from app.services.llm import ChatResponse

        self.calls += 1
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return ChatResponse(
            text=self._outcome, prompt_tokens=1, completion_tokens=1, model=self._model
        )


@pytest.mark.asyncio
async def test_a_rate_limited_light_model_hands_over_to_the_primary() -> None:
    from app.services.llm import ChatMessage

    light, primary = _Fake("openai/gpt-oss-20b", _Err(429)), _Fake("openai/gpt-oss-120b", "ok")
    chain = FallbackProvider([light, primary], fallback_on_rate_limit=True)
    resp = await chain.chat_with_usage([ChatMessage(role="user", content="q")])
    assert resp.model == "openai/gpt-oss-120b" and primary.calls == 1


@pytest.mark.asyncio
async def test_the_main_chain_still_does_not_fall_back_on_429() -> None:
    from app.services.llm import ChatMessage

    primary, fallback = _Fake("openai/gpt-oss-120b", _Err(429)), _Fake("openai/gpt-oss-20b", "ok")
    with pytest.raises(_Err):
        await FallbackProvider([primary, fallback]).chat_with_usage(
            [ChatMessage(role="user", content="q")]
        )
    assert fallback.calls == 0


def test_only_the_light_chain_falls_back_on_rate_limit(groq_with_light) -> None:
    assert get_provider_for("authoring.quiz")._fallback_on_rate_limit is True
    assert get_provider_for("authoring.lesson")._fallback_on_rate_limit is False
