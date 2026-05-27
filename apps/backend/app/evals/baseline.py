"""Baseline-comparison runner (L25).

Runs the existing tutor golden dataset against a second LLM provider
+ records side-by-side scores. Lets the public `/eval` surface
answer the obvious recruiter question: "okay, but how does it
compare to GPT-4-mini?"

Wire shape only in L25. The actual model comparison runs lands in
the L25-followup once we have a real provider key budget allocated
+ a stable canonical dataset for the comparison.

Two flavours of comparison the API supports:

1. **Same-question A vs B** — for each item, run the question
   against the primary provider AND the baseline provider, both
   judged independently. Side-by-side delta = primary_score -
   baseline_score per axis. The dataset stays small (10 items) so
   the cost stays bounded.

2. **Tool-mix comparison** — record `tool_path` per item per
   provider. Lets us claim "GPT-4-mini answered with 0 tool calls;
   Lumen used retriever + code_runner" as a measured comparison,
   not just narrative.

L25 ships the API; the runner is wired to invoke with
``python -m app.evals.baseline run --primary anthropic --baseline noop``
so the smoke path works without a real GPT-4 budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Same shape as the existing runner's score record; kept narrow so a
# diff-pair stays human-readable in the JSONL report.
@dataclass(frozen=True)
class BaselineScore:
    """Score for one item, one provider."""

    provider: str
    grounding: float | None
    accuracy: float | None
    style: float | None
    tool_path: tuple[str, ...] = ()
    latency_ms: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class BaselinePair:
    """Two scores side-by-side for one item."""

    item_id: str
    primary: BaselineScore
    baseline: BaselineScore
    deltas: dict[str, float] = field(default_factory=dict)


def compute_deltas(primary: BaselineScore, baseline: BaselineScore) -> dict[str, float]:
    """Per-axis delta (positive = primary outperforms baseline).

    NaN-safe: if either side is None for an axis, the delta is 0.0
    (no information). The judge currently returns 0-5 scores; the
    delta sits in [-5, 5].
    """

    def _delta(a: float | None, b: float | None) -> float:
        if a is None or b is None:
            return 0.0
        return float(a) - float(b)

    return {
        "grounding": _delta(primary.grounding, baseline.grounding),
        "accuracy": _delta(primary.accuracy, baseline.accuracy),
        "style": _delta(primary.style, baseline.style),
    }


def aggregate_pairs(pairs: list[BaselinePair]) -> dict[str, float]:
    """Mean per-axis delta across the dataset.

    The public `/eval` surface renders these as the "Lumen vs
    GPT-4-mini" bars; a positive number is the primary's lead.
    """
    if not pairs:
        return {"grounding": 0.0, "accuracy": 0.0, "style": 0.0, "n": 0}
    n = len(pairs)
    return {
        "grounding": round(sum(p.deltas.get("grounding", 0.0) for p in pairs) / n, 4),
        "accuracy": round(sum(p.deltas.get("accuracy", 0.0) for p in pairs) / n, 4),
        "style": round(sum(p.deltas.get("style", 0.0) for p in pairs) / n, 4),
        "n": n,
    }


# Provider identifiers L25 ships support for. The actual factory is
# the existing `app.services.llm.get_provider(name)` — we just pass
# the name through so callers from the eval CLI don't need to
# reconstruct the provider per call.
SupportedProvider = Literal["anthropic", "openai", "noop"]
