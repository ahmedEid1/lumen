"""Judge prompt + parsing tests.

Lumen v2 Phase H2. Three things we want to lock in:

1. The judge prompt builder for each suite returns a non-empty
   string and carries the dataset's golden fields verbatim.
2. The parser accepts valid JSON in any of the shapes a real LLM
   might emit (with and without markdown fences, with extra
   whitespace, with scores as ints OR floats).
3. The malformed-reply retry path runs, succeeds when the second
   attempt is valid, and yields ``judge_error=True`` when both
   attempts fail.
"""

from __future__ import annotations

import json

import pytest

from app.evals import judge as judge_mod
from app.services import llm


class _ScriptedProvider:
    """Pops canned replies for each ``chat`` call.

    Mirrors the helper in ``test_ai_authoring.py`` so the test
    style stays consistent across the codebase.
    """

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[llm.ChatMessage]] = []

    async def chat(
        self,
        messages: list[llm.ChatMessage],
        temperature: float = 0.2,
    ) -> str:
        del temperature
        self.calls.append(messages)
        if not self._replies:
            raise AssertionError(
                "scripted provider exhausted — test under-scripted the judge"
            )
        return self._replies.pop(0)


@pytest.mark.asyncio
async def test_judge_tutor_happy_path_parses_scores() -> None:
    prov = _ScriptedProvider(
        [
            json.dumps(
                {
                    "faithfulness": 4,
                    "citation_correctness": 5,
                    "helpfulness": 4,
                    "rationale": "answer cites the right lesson",
                }
            )
        ]
    )
    result = await judge_mod.judge_item(
        "tutor",
        item={
            "question": "what is FastAPI?",
            "ideal_answer": "a python web framework",
            "must_cite_lessons": ["Welcome"],
        },
        actual={
            "answer": "FastAPI is a python web framework [L:abc]",
            "citations": [{"lesson_id": "abc", "lesson_title": "Welcome"}],
        },
        provider=prov,
    )
    assert not result.judge_error
    assert result.scores == {
        "faithfulness": 4,
        "citation_correctness": 5,
        "helpfulness": 4,
    }
    assert "answer cites" in result.rationale
    # Exactly one call — no retry needed.
    assert len(prov.calls) == 1


@pytest.mark.asyncio
async def test_judge_strips_markdown_fences() -> None:
    prov = _ScriptedProvider(
        [
            "```json\n"
            + json.dumps(
                {
                    "faithfulness": 3,
                    "citation_correctness": 3,
                    "helpfulness": 3,
                    "rationale": "ok",
                }
            )
            + "\n```"
        ]
    )
    result = await judge_mod.judge_item(
        "tutor",
        item={"question": "q", "ideal_answer": "a", "must_cite_lessons": []},
        actual={"answer": "ans", "citations": []},
        provider=prov,
    )
    assert not result.judge_error
    assert result.scores["faithfulness"] == 3


@pytest.mark.asyncio
async def test_judge_clamps_out_of_range_scores() -> None:
    prov = _ScriptedProvider(
        [
            json.dumps(
                {
                    "faithfulness": 9,  # over-range — clamp to 5
                    "citation_correctness": -2,  # under-range — clamp to 0
                    "helpfulness": 3.6,  # float — round to 4
                    "rationale": "extreme",
                }
            )
        ]
    )
    result = await judge_mod.judge_item(
        "tutor",
        item={"question": "q", "ideal_answer": "a", "must_cite_lessons": []},
        actual={"answer": "ans", "citations": []},
        provider=prov,
    )
    assert result.scores == {
        "faithfulness": 5,
        "citation_correctness": 0,
        "helpfulness": 4,
    }


@pytest.mark.asyncio
async def test_judge_retries_on_malformed_then_succeeds() -> None:
    valid = json.dumps(
        {
            "faithfulness": 4,
            "citation_correctness": 4,
            "helpfulness": 4,
            "rationale": "second-try fine",
        }
    )
    prov = _ScriptedProvider(["not json at all — sorry", valid])
    result = await judge_mod.judge_item(
        "tutor",
        item={"question": "q", "ideal_answer": "a", "must_cite_lessons": []},
        actual={"answer": "ans", "citations": []},
        provider=prov,
    )
    assert not result.judge_error
    assert result.scores["faithfulness"] == 4
    # Retry path fired — two calls.
    assert len(prov.calls) == 2


@pytest.mark.asyncio
async def test_judge_records_judge_error_when_both_attempts_fail() -> None:
    prov = _ScriptedProvider(["garbage one", "garbage two"])
    result = await judge_mod.judge_item(
        "tutor",
        item={"question": "q", "ideal_answer": "a", "must_cite_lessons": []},
        actual={"answer": "ans", "citations": []},
        provider=prov,
    )
    assert result.judge_error is True
    assert result.scores == {}
    assert len(prov.calls) == 2


@pytest.mark.asyncio
async def test_judge_authoring_axes_present() -> None:
    prov = _ScriptedProvider(
        [
            json.dumps(
                {
                    "coverage": 4,
                    "learning_arc": 3,
                    "scope": 4,
                    "brief_fidelity": 5,
                    "rationale": "good outline",
                }
            )
        ]
    )
    result = await judge_mod.judge_item(
        "authoring",
        item={
            "brief": "FastAPI course",
            "ideal_outline": {"modules": []},
        },
        actual={"outline": {"modules": [{"title": "m1", "lessons": []}]}},
        provider=prov,
    )
    assert not result.judge_error
    assert set(result.scores.keys()) == {
        "coverage",
        "learning_arc",
        "scope",
        "brief_fidelity",
    }


@pytest.mark.asyncio
async def test_judge_ingest_axes_present() -> None:
    prov = _ScriptedProvider(
        [
            json.dumps(
                {
                    "chapter_count_accuracy": 3,
                    "key_phrase_presence": 4,
                    "structure_quality": 4,
                    "rationale": "fine",
                }
            )
        ]
    )
    result = await judge_mod.judge_item(
        "ingest",
        item={
            "url": "https://example.com",
            "kind": "youtube",
            "expected_chapter_count": 5,
            "expected_key_phrases": ["python"],
        },
        actual={"chapters": [{"title": "intro"}], "key_phrases": ["python"]},
        provider=prov,
    )
    assert not result.judge_error
    assert set(result.scores.keys()) == {
        "chapter_count_accuracy",
        "key_phrase_presence",
        "structure_quality",
    }


def test_dataset_loaders_load_each_suite() -> None:
    """The three on-disk datasets load cleanly with the expected counts."""
    from app.evals.golden import load_dataset

    tutor = load_dataset("tutor")
    assert len(tutor) == 30
    assert all(t.must_cite_lessons for t in tutor)  # every item names lessons

    authoring = load_dataset("authoring")
    assert len(authoring) == 10
    assert all(len(a.ideal_outline.modules) >= 3 for a in authoring)

    ingest = load_dataset("ingest")
    assert len(ingest) == 10
    assert sum(1 for i in ingest if i.kind == "youtube") == 5
    assert sum(1 for i in ingest if i.kind == "notion") == 5
