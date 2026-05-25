# Evaluation reports

This directory holds *checked-in* eval artifacts for the README badge and for
portfolio reviewers who want to see the harness output without spinning up the
stack.

## Latest real runs (2026-05-25, Groq Llama 3.3 70B)

| File | Suite | n | Mean overall | Notes |
|------|-------|---|--------------|-------|
| [`authoring-n10-groq-20260525.jsonl`](authoring-n10-groq-20260525.jsonl) | authoring | 10 | **3.85/5** | 10/10 judged, no errors. Axes: coverage 4.0, learning_arc 3.9, scope 4.0, brief_fidelity 3.5. |
| [`tutor-n30-groq-cloudflare-20260525.jsonl`](tutor-n30-groq-cloudflare-20260525.jsonl) | tutor | 30 | **2.33/5** | 10/30 judged, 20 skipped. Real retrieval (Cloudflare Workers AI `@cf/baai/bge-small-en-v1.5`, 384-dim, free tier) + real LLM (Groq Llama 3.3 70B). Faithfulness 3.3, helpfulness 2.8, citation_correctness 0.9 — the low citation score reflects a mismatch between the dataset's expected `must_cite_ids` and what the retriever pulls. |
| [`tutor-n30-groq-noopembed-20260525.jsonl`](tutor-n30-groq-noopembed-20260525.jsonl) | tutor | 30 | 2.0/5 (prior) | Same suite, run with noop embeddings before Cloudflare was wired. Kept for direct comparison: noop → real bumped helpfulness 0.8 → 2.8. |
| [`ingest-n10-groq-20260525.jsonl`](ingest-n10-groq-20260525.jsonl) | ingest | 10 | 0.83/5 | 4/10 judged (6 upstream transcript fetch failures). Judged items scored low on chapter-count + structure because the v1 chunker emits one-module-per-video instead of detecting chapter boundaries. |

## Earlier artifacts (kept for transparency)

| File | Notes |
|------|-------|
| [`tutor-smoke-n3.jsonl`](tutor-smoke-n3.jsonl) | 3-item smoke run executed against the `noop` LLM provider on 2026-05-25 *before* the Groq key was wired. All items errored on the missing `sentence-transformers` dep; the summary line confirmed loader + judge plumbing was structurally correct. Kept as a record of the harness chain's failure mode pre-fix. |

## How to mint a new real number

```bash
# .env needs:
#   LLM_PROVIDER=openai
#   OPENAI_API_BASE=https://api.groq.com/openai/v1
#   OPENAI_API_KEY=<your-groq-key>
#   LLM_MODEL=llama-3.3-70b-versatile
# then:
docker compose exec api python -m app.evals --suite authoring     # full n=10
docker compose exec api python -m app.evals --suite tutor         # full n=30
docker compose exec api python -m app.evals --suite ingest        # full n=10
```

Reports are written under `apps/backend/evals/reports/` as JSONL
(`<suite>-<ISO>.jsonl`). Auto-generated reports are gitignored — copy the
file you want to publish here under a curated name (e.g.
`<suite>-n<N>-<provider>-<YYYYMMDD>.jsonl`) and update the README badge.

For the tutor suite to score meaningfully you need real embeddings — either
add `sentence-transformers` to the API image, or set
`EMBEDDING_PROVIDER=openai` + `OPENAI_API_KEY` (note: this requires a real
OpenAI key, not the Groq one — Groq doesn't ship an embeddings endpoint).
