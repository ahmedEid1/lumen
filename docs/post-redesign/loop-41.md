# Loop 41 — Mistral provider + public eval surface + prod-seed workflow

**Date:** 2026-05-27
**Status:** Shipped

## Goal

Three threads merged into one operator-facing bundle:

1. **Demo regression fix.** The `/demo` redirect targets
   `/learn/typescript-variance`, but the L20.5 TS Generics/Variance
   seed never ran on prod → 404. Cause: `LUMEN_ALLOW_PROD_SEED`
   refusal in `cli.py`. Fix: a one-shot `prod-seed.yml` workflow
   the operator fires from `gh workflow run`.
2. **Free-tier eval baseline.** Wire Mistral as a real LLM provider
   (free-tier OpenAI-compatible API) so the L36 baseline runner has
   a credible-but-free comparator. Cost: $0 vs the original
   GPT-4-mini-as-baseline plan's ~$5.
3. **Public eval surface promotion.** `GET /api/v1/eval/public` +
   `python -m app.cli promote-eval` — the operator publishes a real
   eval report to the public `/eval` page only when ready.

## What shipped

### Mistral provider (`MistralProvider`, OpenAI-compatible)

Mistral La Plateforme exposes `/v1/chat/completions` with the
OpenAI wire shape — same `messages` array, same
`usage.prompt_tokens`/`completion_tokens` on response. So
`MistralProvider(OpenAIProvider)` is a single-line inheritance that
swaps `name="mistral"` for logging + cost attribution. Everything
else (sync chat, lazy SDK import, transport) is inherited.

- `app/services/llm.py` — new class + `get_provider` branch
- `app/services/llm_stream.py` — new `mistral` branch in
  `stream_chat()` that dispatches into the shared
  `_stream_chat_openai_compat` core (refactored from
  `_stream_chat_openai`). Both share the streaming + usage
  extraction logic; only the base URL + key + model differ.
- `app/core/config.py` — `mistral_api_key`, `mistral_api_base`
  (default `https://api.mistral.ai/v1`), `mistral_model` (default
  `mistral-small-latest`).
- `docker-compose.prod.yml` — `MISTRAL_API_KEY`,
  `MISTRAL_API_BASE`, `MISTRAL_MODEL` added to the `x-api-env`
  anchor (same fix pattern as L33 — env vars need explicit
  passthrough or they no-op).

**Verified live:** Mistral key probe against the real API returned
200 + valid content + usage payload.

### Public eval surface (`GET /api/v1/eval/public`)

- `app/api/v1/eval_public.py` — new module. Returns the latest
  *promoted* report per suite, or `null` if the suite isn't
  promoted. Narrow response shape: just the axis means + judge
  metadata + counts (no per-item answers / no raw judge
  rationales — those stay admin-only).
- Promotion ledger: `apps/backend/evals/reports/PROMOTED.json`.
  Tiny JSON dict `{suite: report_id}`. Operator writes via:
  ```
  python -m app.cli promote-eval --suite tutor --report <id>
  ```
  Un-promote with `--clear`. Idempotent. Safe to run against prod
  (no LLM cost, no DB write — just a file edit).
- **Honest-empty contract preserved**: until promotion, every
  suite returns `null` → the public `/eval` page shows placeholders.

### Operator baseline-comparison CLI

- `app/evals/run_baseline.py` — typer CLI that wraps the L36
  `run_comparison`:
  ```
  python -m app.evals.run_baseline run \
    --suite tutor \
    --primary groq-llama-3.3 \
    --primary-base https://api.groq.com/openai/v1 \
    --primary-model llama-3.3-70b-versatile \
    --primary-key-env GROQ_API_KEY \
    --baseline mistral \
    --baseline-base https://api.mistral.ai/v1 \
    --baseline-model mistral-small-latest \
    --baseline-key-env MISTRAL_API_KEY \
    --judge-base https://api.groq.com/openai/v1 \
    --judge-model llama-3.1-8b-instant \
    --judge-key-env GROQ_API_KEY \
    --limit 10
  ```
- Each item runs through both providers via OpenAI-compatible
  endpoints; the judge model scores each answer on
  (grounding/accuracy/style) 0-5.
- Output: `apps/backend/evals/reports/baseline-<suite>-<ts>.jsonl`
  with one row per item + a trailing `_summary` row in the
  `admin_evals.list_reports` shape.
- The CLI prints the resulting `report_id`; operator promotes via
  `promote-eval`.

### Prod-seed workflow

- `.github/workflows/prod-seed.yml` — manual `workflow_dispatch`,
  approval-gated, idempotent. Sets `LUMEN_ALLOW_PROD_SEED=1` for
  the duration of the docker exec (NOT persisted to
  `.env.production`), runs `python -m app.cli demo-seed`, then
  smoke-tests `/api/v1/courses/by-slug/typescript-variance`
  returns 200.
- Requires the operator to type `yes-seed-production` in the
  workflow_dispatch input — defense in depth.

## Tests (35 pass)

- `tests/test_mistral_provider.py` — 4 tests:
  inheritance, `get_provider` resolves to Mistral with the right
  base+key, streaming branch requires the key, streaming uses the
  Mistral base+key+model (mocked SDK).
- `tests/test_eval_public.py` — 5 tests:
  honest-empty when nothing promoted, promoted summary surfaces
  axes, promoted-but-missing-file degrades to null,
  set/clear/get round-trip, set rejects unknown suite.
- `tests/test_llm_stream.py` — 5 unchanged tests still pass after
  the OpenAI-compat core refactor.
- `tests/test_baseline_eval.py` — 8 unchanged tests still pass.

Frontend `pnpm tsc --noEmit` clean.

## What the operator does after this deploys

1. **Fire `prod-seed.yml`** once via `gh workflow run prod-seed.yml
   -f confirm=yes-seed-production`. Smoke-test in the workflow
   asserts `typescript-variance` course is reachable.
   `/demo` deep-link works again.
2. **Set `MISTRAL_API_KEY`** on prod via flip-flag-style ssh OR by
   adding to `.env.production` directly. The key the user shared
   in chat needs to be **rotated** via Mistral console before
   adding to prod env (chat history leak).
3. **Run the eval CLI** once:
   ```
   docker compose -f docker-compose.prod.yml exec api \
     python -m app.evals.run_baseline run \
     --suite tutor --primary groq-llama-3.3 \
     --primary-base https://api.groq.com/openai/v1 \
     --primary-model llama-3.3-70b-versatile \
     --baseline mistral --baseline-model mistral-small-latest \
     --judge-base https://api.groq.com/openai/v1 \
     --judge-model llama-3.1-8b-instant \
     --limit 10
   ```
   Cost: $0 (all free tiers).
4. **Promote** the resulting report:
   ```
   python -m app.cli promote-eval --suite tutor --report <id>
   ```
5. Verify `https://lumen.ahmedhobeishy.tech/api/v1/eval/public`
   returns the summary.
6. Public `/eval` page now shows real numbers.

## Deferred (still operator-OK gates)

- Repo rename `E-Learning-Platform` → `lumen`
- Distribution drafts going public
- Canonical demo question lockdown (after 10/10 tool-sequence eval gate)
