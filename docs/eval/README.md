# Evaluation reports

This directory holds *checked-in* eval artifacts for the README badge and for
portfolio reviewers who want to see the harness output without spinning up the
stack.

## Latest real runs (2026-05-25, Groq Llama 3.3 70B)

Groq Llama 3.3 70B was both the model and the judge in these runs. It has
since been retired; production now runs on Groq `openai/gpt-oss-120b`. The
scores below come from the older setup.

| File | Suite | n | Mean overall | Notes |
|------|-------|---|--------------|-------|
| [`authoring-n10-groq-20260525.jsonl`](authoring-n10-groq-20260525.jsonl) | authoring | 10 | **3.85/5** | 10/10 judged, no errors. Axes: coverage 4.0, learning_arc 3.9, scope 4.0, brief_fidelity 3.5. |
| [`tutor-n30-groq-cloudflare-20260525.jsonl`](tutor-n30-groq-cloudflare-20260525.jsonl) | tutor | 30 | **2.33/5** | 10/30 judged, 20 skipped. Real retrieval (Cloudflare Workers AI `@cf/baai/bge-small-en-v1.5`, 384-dim, free tier) + real LLM (Groq Llama 3.3 70B). Faithfulness 3.3, helpfulness 2.8, citation_correctness 0.9. The low citation score comes from a label bug: the synthesiser headed each excerpt `Lesson L<id>`, the model cited `[L:L<id>]`, and validation dropped those citations because lesson ids have no `L` prefix. 6 of the 7 answers that didn't refuse cited the right lesson in that form (t-001 to t-005, t-009). The fix is in [PR #21](https://github.com/ahmedEid1/lumen/pull/21); the suite has not been re-run since. The 20 skipped items belong to two courses that were not seeded (`data-science-foundations`, `react-essentials`). |
| [`tutor-n30-groq-noopembed-20260525.jsonl`](tutor-n30-groq-noopembed-20260525.jsonl) | tutor | 30 | 2.0/5 (prior) | Same suite, run with noop embeddings before Cloudflare was wired. Kept for direct comparison: noop → real bumped helpfulness 0.8 → 2.8. |
| [`ingest-n10-groq-20260525.jsonl`](ingest-n10-groq-20260525.jsonl) | ingest | 10 | 0.83/5 | 4/10 judged, 6 errors. i-002: a 465-lesson video broke the 200-lesson module cap (`ValidationError`). i-006: `NOTION_TOKEN` was not set in the eval env. i-007 to i-010: the dataset URLs are Notion help-center pages with no page ID. Judged items scored low on chapter-count + structure because the v1 chunker emits one-module-per-video instead of detecting chapter boundaries. |

## Earlier artifacts (kept for transparency)

| File | Notes |
|------|-------|
| [`tutor-smoke-n3.jsonl`](tutor-smoke-n3.jsonl) | 3-item smoke run executed against the `noop` LLM provider on 2026-05-25 *before* the Groq key was wired. All items errored on the missing `sentence-transformers` dep; the summary line confirmed loader + judge plumbing was structurally correct. Kept as a record of the harness chain's failure mode pre-fix. |

## CI smoke

[`.github/workflows/pnpm-eval-smoke.yml`](../../.github/workflows/pnpm-eval-smoke.yml)
runs 3 tutor items on every PR. The repo has no model key secret, so the
smoke runs on the `noop` LLM and noop embeddings, and the score gate
(`mean_overall >= 3.5`) is skipped. It exercises the harness code path; it
does not check the scores.

## How to mint a new real number

```bash
# .env needs:
#   LLM_PROVIDER=openai
#   OPENAI_API_BASE=https://api.groq.com/openai/v1
#   OPENAI_API_KEY=<your-groq-key>
#   LLM_MODEL=openai/gpt-oss-120b
# then:
docker compose exec api python -m app.evals run --suite authoring     # full n=10
docker compose exec api python -m app.evals run --suite tutor         # full n=30
docker compose exec api python -m app.evals run --suite ingest        # full n=10
```

Reports are written under `apps/backend/evals/reports/` as JSONL
(`<suite>-<ISO>.jsonl`). Auto-generated reports are gitignored — copy the
file you want to publish here under a curated name (e.g.
`<suite>-n<N>-<provider>-<YYYYMMDD>.jsonl`) and update the README badge.

For the tutor suite to score meaningfully you need real embeddings. Either
add `sentence-transformers` to the API image, or set
`EMBEDDING_PROVIDER=openai` and point it at any OpenAI-compatible embeddings
endpoint with `EMBEDDING_OPENAI_API_BASE` and `EMBEDDING_OPENAI_API_KEY`
(they fall back to `OPENAI_API_BASE` / `OPENAI_API_KEY` when unset). Production
uses Cloudflare Workers AI this way
(`EMBEDDING_OPENAI_API_BASE=https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1`,
`EMBEDDING_MODEL_OPENAI=@cf/baai/bge-small-en-v1.5`). Groq has no embeddings
endpoint, so the Groq key alone is not enough.
