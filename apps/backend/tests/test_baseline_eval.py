"""Baseline-comparison delta math (L25)."""

from __future__ import annotations

from app.evals.baseline import (
    BaselinePair,
    BaselineScore,
    aggregate_pairs,
    compute_deltas,
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
