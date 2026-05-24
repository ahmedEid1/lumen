"""CLI: ``python -m app.evals run --suite tutor [--limit N] [--out FILE]``.

Lumen v2 Phase H2. This is the dispatch entrypoint for CI's smoke
gate and the operator's manual runs. Reuses Typer (already a
backend dependency for ``app.cli``) so the help/style matches the
rest of the project.

Typer note
==========
A no-op ``@cli.callback()`` is registered below so Typer keeps
``run`` exposed as an explicit subcommand. Without it Typer
collapses a single-command app to a flat invocation
(``python -m app.evals --suite tutor``), which silently breaks
every doc + CI step that already calls the documented
``python -m app.evals run --suite tutor`` form. Keep the callback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from app.evals.golden import SUITES, SuiteName
from app.evals.runner import run_suite

cli = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@cli.callback()
def _root() -> None:
    """Lumen eval harness — golden datasets, LLM-as-judge, JSONL reports.

    The callback is intentionally a no-op; it exists so Typer keeps
    ``run`` as an explicit subcommand instead of collapsing the
    single-command app to a flat invocation. See the module
    docstring for the why.
    """


@cli.command()
def run(
    suite: str = typer.Option(..., "--suite", help=f"One of {list(SUITES)}"),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Run only the first N items (smoke-test mode)"
    ),
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Path to write the JSONL report (default: evals/reports/<suite>-<ISO>.jsonl)",
    ),
    judge_model: Optional[str] = typer.Option(
        None,
        "--judge-model",
        help="Override the model name recorded on the report summary. The "
        "active LLM provider is still selected via LLM_PROVIDER / LLM_MODEL.",
    ),
) -> None:
    """Run a golden eval suite end-to-end."""
    if suite not in SUITES:
        raise typer.BadParameter(f"--suite must be one of {list(SUITES)}")

    path = asyncio.run(
        run_suite(
            suite=suite,  # type: ignore[arg-type]
            limit=limit,
            out_path=out,
            judge_model=judge_model,
        )
    )
    console.print(f"[green]wrote report:[/green] {path}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
