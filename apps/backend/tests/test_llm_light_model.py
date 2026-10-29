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
