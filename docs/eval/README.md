# Evaluation reports

This directory holds *checked-in* eval artifacts for the README badge and for
portfolio reviewers who want to see the harness output without spinning up the
stack.

## Files

- [`tutor-smoke-n3.jsonl`](tutor-smoke-n3.jsonl) — 3-item smoke run of the
  tutor suite executed against the `noop` LLM provider on 2026-05-25. Verifies
  the full harness chain (item loader → executor → judge → reporter →
  JSONL report) without needing a real LLM key or a retrieval-embedding
  model. Items end up `status=error` because the retriever wants the local
  `sentence-transformers` embedding model and the slim API image doesn't
  bundle PyTorch by default — this is the same surface every reviewer would
  hit on first run without setting `OPENAI_EMBEDDINGS_KEY` or installing
  `sentence-transformers`. The summary line at the bottom confirms loader +
  judge plumbing are correct.

## How to mint a real number

```bash
# locally, against the docker-compose stack:
docker compose exec api python -m app.evals --suite tutor          # full n=30
docker compose exec api python -m app.evals --suite authoring      # n=10
docker compose exec api python -m app.evals --suite ingest         # n=10
```

Reports are written under `apps/backend/evals/reports/` as JSONL
(`<suite>-<ISO>.jsonl`). The auto-generated reports are gitignored — copy
the file you want to publish here under a curated name (e.g.
`tutor-n30-groq-20260601.jsonl`) and update the README badge.

For the judge call to score (vs. error) you need an LLM provider key set in
`.env` — Groq's free Llama 3.3 70B is the recommended starting point. For
retrieval-based suites (tutor, ingest) you also need either
`sentence-transformers` installed in the API image **or** `OPENAI_API_KEY` +
`OPENAI_EMBEDDINGS_MODEL=text-embedding-3-small` set so the embedding
provider switches to OpenAI.
