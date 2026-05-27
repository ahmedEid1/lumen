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

import contextlib
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


# ---------- L36 — real comparison runner ----------


@dataclass(frozen=True)
class BaselineItem:
    """One question to evaluate side-by-side.

    The dataset stays small (10 items targeted; the public /eval
    surface only needs aggregate deltas, not per-item detail). Each
    item carries the question + the canonical lesson IDs the
    grounded answer SHOULD cite — the judge keys grounding off that.
    """

    item_id: str
    question: str
    expected_lesson_ids: tuple[str, ...] = ()
    expected_tool_path: tuple[str, ...] = ()


async def run_one_item(
    item: BaselineItem,
    *,
    provider_name: str,
    answer_fn,
    score_fn,
) -> BaselineScore:
    """Run a single item against one provider + score the result.

    Caller plugs in:
    - ``answer_fn(question, provider_name) -> (answer_text, tool_path, latency_ms, cost_usd)``
      Lets tests pass a stub without spinning up the orchestrator.
    - ``score_fn(item, answer_text, tool_path) -> (grounding, accuracy, style)``
      Lets tests pass a deterministic scorer instead of an LLM judge.

    Keeping both as parameters means the same `run_one_item` function
    works for the noop smoke path AND the eventual real-LLM
    comparison once budget is allocated — only the closures change.
    """
    answer_text, tool_path, latency_ms, cost_usd = await answer_fn(item.question, provider_name)
    grounding, accuracy, style = await score_fn(item, answer_text, tool_path)
    return BaselineScore(
        provider=provider_name,
        grounding=grounding,
        accuracy=accuracy,
        style=style,
        tool_path=tuple(tool_path),
        latency_ms=int(latency_ms),
        cost_usd=float(cost_usd),
    )


async def run_comparison(
    items: list[BaselineItem],
    *,
    primary: str,
    baseline: str,
    answer_fn,
    score_fn,
    on_item_error=None,
) -> list[BaselinePair]:
    """Run the full dataset against `primary` and `baseline` providers.

    Returns one BaselinePair per item with per-axis deltas computed.
    Callers serialise this to JSONL for the /eval surface; the
    aggregate is `aggregate_pairs(pairs)`.

    Cost guard: ``answer_fn`` is expected to report cost_usd; the
    caller should short-circuit once the cumulative cost crosses
    their budget (this function doesn't enforce a budget itself —
    the caller's runtime knows what's affordable).

    L39 rescue (Codex P2): each item runs inside a try/except so a
    failure on item N (rate limit / provider timeout / judge error)
    does NOT throw away the N-1 prior pairs already paid for. The
    optional ``on_item_error(item, exc)`` callback lets callers log
    or persist the failure — by default it's a no-op.
    """
    pairs: list[BaselinePair] = []
    for item in items:
        try:
            primary_score = await run_one_item(
                item, provider_name=primary, answer_fn=answer_fn, score_fn=score_fn
            )
            baseline_score = await run_one_item(
                item, provider_name=baseline, answer_fn=answer_fn, score_fn=score_fn
            )
        except Exception as exc:
            if on_item_error is not None:
                # Best-effort: a bad callback shouldn't crash the run.
                with contextlib.suppress(Exception):
                    res = on_item_error(item, exc)
                    if hasattr(res, "__await__"):
                        await res
            continue
        pairs.append(
            BaselinePair(
                item_id=item.item_id,
                primary=primary_score,
                baseline=baseline_score,
                deltas=compute_deltas(primary_score, baseline_score),
            )
        )
    return pairs
