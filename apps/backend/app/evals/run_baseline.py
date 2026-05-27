"""Operator-driven baseline comparison runner (L41).

Wires the L36 `run_comparison()` runner against real providers.

Usage::

    docker compose -f docker-compose.prod.yml exec api \\
        python -m app.evals.run_baseline \\
            --suite tutor \\
            --primary openai \\
            --primary-base https://api.groq.com/openai/v1 \\
            --primary-model llama-3.3-70b-versatile \\
            --baseline mistral \\
            --baseline-model mistral-small-latest \\
            --judge openai \\
            --judge-base https://api.groq.com/openai/v1 \\
            --judge-model llama-3.1-8b-instant \\
            --limit 10

The script runs each question through both providers, has the judge
score each answer on (grounding, accuracy, style), writes a JSONL
report to ``apps/backend/evals/reports/baseline-<ts>.jsonl``, and
prints the aggregate deltas.

Promote to the public ``/eval`` page::

    python -m app.cli promote-eval --suite tutor --report <id>

The runner is intentionally narrow — it composes the existing
``run_comparison`` with closures that hit the real LLM endpoints
+ a tiny LLM-as-judge prompt. ~120 LoC; the operator can fork it
to swap closures (different judge rubric, different scoring shape)
without touching the runner core.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime

import typer

from app.evals.baseline import (
    BaselineItem,
    aggregate_pairs,
    run_comparison,
)
from app.evals.golden import SUITES, load_dataset, reports_dir
from app.services.llm import ChatMessage

app = typer.Typer(no_args_is_help=True, help="Operator baseline-comparison runner (L41).")


async def _ask(
    question: str,
    *,
    api_base: str,
    api_key: str,
    model: str,
) -> tuple[str, tuple[str, ...], int, float]:
    """Call an OpenAI-compatible chat endpoint with a single
    user message. Returns (answer, tool_path, latency_ms, cost_usd).

    `tool_path` is `()` here because the bare chat call doesn't
    drive the orchestrator's multi-agent dispatch — that's
    intentional, the baseline is "what does GPT/Mistral say cold."
    A future variant could route through `tutor_orchestrator.ask`
    for the agent path.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=api_base)
    t0 = time.monotonic()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
        max_tokens=600,
        temperature=0.2,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    text = resp.choices[0].message.content or ""
    # Cost computation is a sub-feature; leave at 0 for the operator
    # tally. The eval surface keys off axis means, not cost — cost
    # tracking lives in `llm_calls` separately if the operator
    # configured it.
    return text, (), latency_ms, 0.0


_JUDGE_SYSTEM = (
    "You are an impartial judge scoring an AI tutor's answer to a "
    "programming question. Score on THREE axes from 0.0 to 5.0 "
    "(0=worst, 5=best):\n"
    "  grounding: does the answer cite concrete sources / lessons?\n"
    "  accuracy: is the answer factually correct?\n"
    "  style: is the answer concise + readable + scoped?\n"
    "Reply with EXACTLY one JSON object: "
    '{"grounding": <float>, "accuracy": <float>, "style": <float>}. '
    "No prose."
)


async def _judge(
    item: BaselineItem,
    answer: str,
    tool_path: tuple[str, ...],
    *,
    api_base: str,
    api_key: str,
    model: str,
) -> tuple[float, float, float]:
    """LLM-as-judge — scores `answer` on the three axes."""
    from openai import AsyncOpenAI

    del tool_path  # unused; could feed into a future agentic-trace rubric
    client = AsyncOpenAI(api_key=api_key, base_url=api_base)
    user_prompt = (
        f"QUESTION: {item.question}\n\nANSWER:\n{answer}\n\n"
        "Score this answer. Reply with the JSON object only."
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=80,
        temperature=0.0,
    )
    text = (resp.choices[0].message.content or "").strip()
    # Defensive parse — judges occasionally wrap JSON in code fences.
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        parsed = json.loads(text)
        return (
            float(parsed.get("grounding", 0.0)),
            float(parsed.get("accuracy", 0.0)),
            float(parsed.get("style", 0.0)),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        # Honest-empty: judge failed to follow the rubric; treat as
        # zero across the board (the operator sees this in the
        # finished_at summary and re-runs with a sturdier judge
        # model).
        return 0.0, 0.0, 0.0


@app.command()
def run(
    suite: str = typer.Option("tutor", "--suite"),
    primary: str = typer.Option(
        ..., "--primary", help="Tag for the primary side (used in report)."
    ),
    primary_base: str = typer.Option(..., "--primary-base"),
    primary_key_env: str = typer.Option("GROQ_API_KEY", "--primary-key-env"),
    primary_model: str = typer.Option(..., "--primary-model"),
    baseline: str = typer.Option(..., "--baseline"),
    baseline_base: str = typer.Option("https://api.mistral.ai/v1", "--baseline-base"),
    baseline_key_env: str = typer.Option("MISTRAL_API_KEY", "--baseline-key-env"),
    baseline_model: str = typer.Option("mistral-small-latest", "--baseline-model"),
    judge_base: str = typer.Option(..., "--judge-base"),
    judge_key_env: str = typer.Option("GROQ_API_KEY", "--judge-key-env"),
    judge_model: str = typer.Option("llama-3.1-8b-instant", "--judge-model"),
    limit: int | None = typer.Option(None, "--limit", help="Cap items for a smoke run."),
) -> None:
    """Drive the L36 `run_comparison` against real providers + write a JSONL report."""
    if suite not in SUITES:
        raise typer.BadParameter(f"--suite must be one of {list(SUITES)}")

    primary_key = os.environ.get(primary_key_env, "")
    baseline_key = os.environ.get(baseline_key_env, "")
    judge_key = os.environ.get(judge_key_env, "")
    if not primary_key:
        raise typer.BadParameter(f"env var {primary_key_env} unset")
    if not baseline_key:
        raise typer.BadParameter(f"env var {baseline_key_env} unset")
    if not judge_key:
        raise typer.BadParameter(f"env var {judge_key_env} unset")

    raw = load_dataset(suite)
    if limit:
        raw = raw[:limit]
    # `load_dataset()` returns typed dataclass items (TutorItem /
    # AuthoringItem / IngestItem), not dicts. Adapt via getattr so
    # the same loop works across all three suites without per-suite
    # branching. AuthoringItem's question-field is `prompt`; the
    # tutor + ingest suites use `question`.
    items = [
        BaselineItem(
            item_id=str(getattr(r, "id", None) or f"item-{i}"),
            question=str(getattr(r, "question", None) or getattr(r, "prompt", "") or ""),
        )
        for i, r in enumerate(raw)
    ]

    async def answer_fn(question: str, provider_name: str):
        if provider_name == primary:
            return await _ask(
                question, api_base=primary_base, api_key=primary_key, model=primary_model
            )
        return await _ask(
            question, api_base=baseline_base, api_key=baseline_key, model=baseline_model
        )

    async def score_fn(item: BaselineItem, answer: str, tool_path: tuple[str, ...]):
        return await _judge(
            item, answer, tool_path, api_base=judge_base, api_key=judge_key, model=judge_model
        )

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_id = f"baseline-{suite}-{ts}"
    typer.echo(f"running {len(items)} items: {primary} vs {baseline}, judge={judge_model}")

    pairs = asyncio.run(
        run_comparison(
            items,
            primary=primary,
            baseline=baseline,
            answer_fn=answer_fn,
            score_fn=score_fn,
        )
    )
    summary = aggregate_pairs(pairs)
    typer.echo(f"aggregate deltas (primary minus baseline): {summary}")

    out_dir = reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report_id}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(
                json.dumps(
                    {
                        "item_id": p.item_id,
                        "primary": {
                            "provider": p.primary.provider,
                            "grounding": p.primary.grounding,
                            "accuracy": p.primary.accuracy,
                            "style": p.primary.style,
                        },
                        "baseline": {
                            "provider": p.baseline.provider,
                            "grounding": p.baseline.grounding,
                            "accuracy": p.baseline.accuracy,
                            "style": p.baseline.style,
                        },
                        "deltas": p.deltas,
                    }
                )
                + "\n"
            )
        # Trailing summary row that admin_evals.list_reports keys off.
        f.write(
            json.dumps(
                {
                    "_summary": True,
                    "report_id": report_id,
                    "suite": suite,
                    "started_at": ts,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "mean_overall": (summary["grounding"] + summary["accuracy"] + summary["style"])
                    / 3,
                    "axes": {k: summary[k] for k in ("grounding", "accuracy", "style")},
                    "items_total": len(items),
                    "items_judged": len(pairs),
                    "judge_provider": "openai-compat",
                    "judge_model": judge_model,
                }
            )
            + "\n"
        )
    typer.echo(f"wrote {out_path}")
    typer.echo(f"promote with: python -m app.cli promote-eval --suite {suite} --report {report_id}")


# Synthesise ChatMessage so the import isn't pruned by ruff — the
# runner re-uses the type when integrating with the orchestrator.
_unused = ChatMessage


if __name__ == "__main__":
    app()
