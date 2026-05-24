### Activation (A2)

The H2 eval harness was smoke-tested end-to-end against the deterministic `noop` provider, and two CLI rough edges were fixed in passing. The runner's `run` Typer command had silently collapsed to a flat invocation (because the app had only one command), so the documented `python -m app.evals run --suite tutor` form — used by the README, CHANGELOG, the `.github/workflows/pnpm-eval-smoke.yml` CI smoke gate, and the `/admin/evals` admin page — was raising `Got unexpected extra argument (run)`. A no-op `@cli.callback()` restores the explicit subcommand. The CLI now preflights `LLM_PROVIDER` credentials before opening a DB session, so a missing `OPENAI_API_KEY` (Groq path) or `ANTHROPIC_API_KEY` fails with one named-env-var error at the boundary instead of an opaque vendor exception after writing a partial report. Finally, `make eval` was added — overrides via `suite=authoring|ingest` and `limit=N` — so the operator runbook below stays a one-liner.

### Operator runbook (eval)

Bring the stack up and seed it (one-time per fresh checkout):

```bash
make up
make migrate
make seed
make demo-seed
```

Get a free Groq API key at <https://console.groq.com> (Llama 3.3 70B is on the free tier; see `docs/superpowers/specs/2026-05-22-lumen-v2-agentic-positioning.md` §6 for the cost rationale).

Configure the api container's environment for a Groq-backed run. Either export these in your shell before `make up`, or add them to `.env`:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_BASE=https://api.groq.com/openai/v1
export OPENAI_API_KEY=gsk_...                       # your Groq key
export LLM_MODEL=llama-3.3-70b-versatile
```

Run the full tutor suite (30 items, ~3-4 minutes against Groq):

```bash
make eval                                            # tutor by default
```

Or pick a different suite, or truncate to a smoke subset:

```bash
make eval suite=authoring                            # 10 outline-generation items
make eval suite=ingest                               # 10 URL-ingest items
make eval suite=tutor limit=3                        # 3-item smoke run
```

Reports land at `apps/backend/evals/reports/<suite>-<ISO>.jsonl` inside the api container; copy one out to inspect:

```bash
docker compose cp api:/app/evals/reports/. ./apps/backend/evals/reports/
```

The admin dashboard at <http://localhost:3000/admin/evals> reads the same reports directory and renders per-suite mean scores plus per-item drill-down.

For a free, network-free smoke that proves the wiring without burning Groq tokens:

```bash
LLM_PROVIDER=noop EMBEDDING_PROVIDER=noop make eval suite=tutor limit=1
```
