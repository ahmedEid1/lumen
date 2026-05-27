"""Baseline-comparison delta math (L25) + runner wire (L36)."""

from __future__ import annotations

import pytest

from app.evals.baseline import (
    BaselineItem,
    BaselinePair,
    BaselineScore,
    aggregate_pairs,
    compute_deltas,
    run_comparison,
    run_one_item,
)


def test_compute_deltas_positive_means_primary_outperforms() -> None:
    primary = BaselineScore(provider="anthropic", grounding=4.0, accuracy=5.0, style=4.5)
    baseline = BaselineScore(provider="openai", grounding=3.0, accuracy=3.5, style=4.0)
    deltas = compute_deltas(primary, baseline)
    assert deltas["grounding"] == 1.0
    assert deltas["accuracy"] == 1.5
    assert deltas["style"] == 0.5


def test_compute_deltas_handles_none_as_zero() -> None:
    """A None score means the judge didn't fire — delta is 0
    (no information), not NaN."""
    primary = BaselineScore(provider="anthropic", grounding=None, accuracy=4.0, style=4.0)
    baseline = BaselineScore(provider="openai", grounding=3.0, accuracy=None, style=4.0)
    deltas = compute_deltas(primary, baseline)
    assert deltas["grounding"] == 0.0
    assert deltas["accuracy"] == 0.0
    assert deltas["style"] == 0.0


def test_aggregate_pairs_means_per_axis() -> None:
    p1 = BaselinePair(
        item_id="t-1",
        primary=BaselineScore("a", 5.0, 5.0, 5.0),
        baseline=BaselineScore("b", 3.0, 3.0, 3.0),
        deltas={"grounding": 2.0, "accuracy": 2.0, "style": 2.0},
    )
    p2 = BaselinePair(
        item_id="t-2",
        primary=BaselineScore("a", 4.0, 4.0, 4.0),
        baseline=BaselineScore("b", 3.0, 3.0, 3.0),
        deltas={"grounding": 1.0, "accuracy": 1.0, "style": 1.0},
    )
    summary = aggregate_pairs([p1, p2])
    assert summary["grounding"] == 1.5
    assert summary["accuracy"] == 1.5
    assert summary["style"] == 1.5
    assert summary["n"] == 2


def test_aggregate_pairs_empty_returns_zero() -> None:
    summary = aggregate_pairs([])
    assert summary["n"] == 0
    assert summary["grounding"] == 0.0


# ---------- L36 — runner wire ----------


@pytest.mark.asyncio
async def test_run_one_item_threads_results_through() -> None:
    """run_one_item composes the caller's answer_fn + score_fn into
    a BaselineScore. Lets the operator path swap the closures
    without rewriting the loop."""
    item = BaselineItem(item_id="t-1", question="What is a closure?")

    async def fake_answer(question, provider_name):
        # Returns (answer_text, tool_path, latency_ms, cost_usd).
        return "a closure is...", ("retriever",), 120, 0.00024

    async def fake_score(it, answer_text, tool_path):
        # Returns (grounding, accuracy, style).
        return 4.0, 5.0, 4.5

    score = await run_one_item(
        item, provider_name="anthropic", answer_fn=fake_answer, score_fn=fake_score
    )
    assert score.provider == "anthropic"
    assert score.grounding == 4.0
    assert score.accuracy == 5.0
    assert score.style == 4.5
    assert score.tool_path == ("retriever",)
    assert score.latency_ms == 120
    assert score.cost_usd == pytest.approx(0.00024)


@pytest.mark.asyncio
async def test_run_comparison_returns_pairs_with_deltas() -> None:
    """run_comparison drives the full dataset against primary +
    baseline and computes per-item deltas. The aggregate_pairs
    helper is unchanged from L25 so feeding the result through it
    yields the same aggregate shape /eval renders."""
    items = [
        BaselineItem(item_id="t-1", question="Q1?"),
        BaselineItem(item_id="t-2", question="Q2?"),
    ]
    # Primary slightly better than baseline on grounding; identical
    # on accuracy/style. Lets us assert positive deltas come through.
    score_map = {
        "primary": (4.0, 4.0, 4.0),
        "baseline": (3.0, 4.0, 4.0),
    }

    async def fake_answer(question, provider_name):
        return f"answer for {question} ({provider_name})", (), 50, 0.0

    async def fake_score(it, answer_text, tool_path):
        # Decide which "side" we are by sniffing the answer text — a
        # real scorer would judge independently.
        provider = "primary" if "primary" in answer_text else "baseline"
        return score_map[provider]

    pairs = await run_comparison(
        items, primary="primary", baseline="baseline", answer_fn=fake_answer, score_fn=fake_score
    )
    assert len(pairs) == 2
    for pair in pairs:
        assert pair.deltas["grounding"] == 1.0
        assert pair.deltas["accuracy"] == 0.0
        assert pair.deltas["style"] == 0.0

    summary = aggregate_pairs(pairs)
    assert summary["n"] == 2
    assert summary["grounding"] == 1.0
    assert summary["accuracy"] == 0.0
