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

import typer
from rich.console import Console

from app.evals.golden import SUITES
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


def _preflight_provider() -> None:
    """Fail fast when the selected LLM provider has no credentials.

    The runner opens a DB session and iterates the dataset before
    dispatching the first chat call, so a missing key currently
    surfaces as a vendor SDK exception mid-suite (partial report on
    disk, opaque ``RuntimeError``). We check the configured provider
    here so the operator sees one clean message at the CLI boundary
    and points them at the right env var — including the Groq
    OpenAI-compatible setup, since that's the documented free-tier
    path operators will hit first.
    """
    from app.core.config import get_settings

    s = get_settings()
    provider = s.llm_provider
    if provider == "noop":
        return
    if provider == "openai":
        key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
        if not key:
            raise typer.BadParameter(
                "LLM_PROVIDER=openai but OPENAI_API_KEY is unset. "
                "Set it in your environment (or .env) before running the eval. "
                "For a Groq-backed run, also point OPENAI_API_BASE at "
                "https://api.groq.com/openai/v1 and set LLM_MODEL "
                "(e.g. llama-3.3-70b-versatile).",
                param_hint="LLM_PROVIDER",
            )
        return
    if provider == "anthropic":
        key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else ""
        if not key:
            raise typer.BadParameter(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is unset. "
                "Set it in your environment (or .env) before running the eval, "
                "or switch to LLM_PROVIDER=noop for a deterministic smoke run.",
                param_hint="LLM_PROVIDER",
            )


@cli.command()
def run(
    suite: str = typer.Option(..., "--suite", help=f"One of {list(SUITES)}"),
    limit: int | None = typer.Option(
        None, "--limit", help="Run only the first N items (smoke-test mode)"
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Path to write the JSONL report (default: evals/reports/<suite>-<ISO>.jsonl)",
    ),
    judge_model: str | None = typer.Option(
        None,
        "--judge-model",
        help="Override the model name recorded on the report summary. The "
        "active LLM provider is still selected via LLM_PROVIDER / LLM_MODEL.",
    ),
) -> None:
    """Run a golden eval suite end-to-end.

    Provider is picked from LLM_PROVIDER (noop / openai / anthropic);
    LLM_MODEL overrides the per-provider default. For a Groq-backed
    run set LLM_PROVIDER=openai +
    OPENAI_API_BASE=https://api.groq.com/openai/v1 +
    LLM_MODEL=llama-3.3-70b-versatile and put your Groq key in
    OPENAI_API_KEY. See docs/release/operator-activation-runbook.md for the
    full operator runbook.
    """
    if suite not in SUITES:
        raise typer.BadParameter(f"--suite must be one of {list(SUITES)}")

    _preflight_provider()

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
