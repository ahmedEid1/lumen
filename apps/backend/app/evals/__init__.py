"""Eval harness — golden datasets, LLM-as-judge, JSONL reports.

Lumen v2 Phase H2. See ``docs/superpowers/specs/2026-05-22-lumen-v2-agentic-positioning.md``
section 2 item H2 for the why; see ``apps/backend/evals/`` for the
datasets themselves; see ``app/evals/runner.py`` for the entrypoint.
"""

from app.evals.golden import SUITES, SuiteName, load_dataset
from app.evals.judge import JudgeResult, judge_item
from app.evals.runner import run_suite

__all__ = [
    "SUITES",
    "JudgeResult",
    "SuiteName",
    "judge_item",
    "load_dataset",
    "run_suite",
]
