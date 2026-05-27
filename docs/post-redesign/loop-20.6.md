# Loop 20.6 — RAG-from-scratch course + 15-question demo library + streaming obs tile prep

**Date:** 2026-05-27
**Scope:** Continued demo runway for L21+; finishes the L20.x demo-content pair

## What shipped

### Building a RAG system from scratch — new demo course

`apps/backend/app/seeds/rag_from_scratch_demo.py` (new). 4 modules / 8
lessons:

| Module | Lessons |
|---|---|
| What RAG is | Why RAG vs fine-tuning · The hallucination problem · quiz |
| Embeddings 101 | What an embedding is · Cosine similarity + pgvector storage |
| Chunking + retrieval | Why chunking matters · Hybrid (vector + BM25) search |
| Building + evaluating the loop | The end-to-end loop · Evaluating RAG (recall, faithfulness, quality) |

Self-referential by design — the tutor cites these lessons when a
recruiter asks "how does this RAG system work?". Maps 1:1 to the L21
architectural ADRs (0017/0018/0019) so a learner who finishes the
course has a head start on the L30 case study.

Wired into `app/seeds/demo.py::run()`. Demo learner auto-enrolled so
the future "ask the tutor about itself" flow lands on an enrolled
state. Idempotent re-seed verified locally + by test.

### Curated demo-question library (15 questions)

`apps/backend/app/demo_questions.py` (new). 15 questions across 5
categories:

| Category | Count | Examples |
|---|---|---|
| retriever-only | 3 | generic 101, RAG-vs-fine-tuning, async-vs-parallelism |
| retriever-code-runner | 3 | **canonical** (TS variance), N+1 SQLA, cosine similarity numeric |
| retriever-web-searcher | 3 | latest TS features, current FastAPI, new pgvector indexes |
| refusal | 3 | malware, medical, system-prompt-extract |
| multi-hop | 3 | pgvector+async, generic+mapped, RAG-eval reasoning |

Canonical question is `ts-variance-canonical` (the L20.5 TS variance
error). `get_canonical_question()` enforces the "exactly one
canonical" invariant — adding a second canonical raises at load time.
`expected_tools` lists are validated against the known sub-agent
identifiers so a typo (`retriver`) can't silently break the L25 eval
gate.

`GET /api/v1/demo-questions?course_slug=<slug>` exposes the library
read-only. Anon-readable — the L22 chip rail renders before sign-in
on `/demo`. Returns version + canonical id alongside the list.
Frontend hook `useDemoQuestions(courseSlug)` in
`apps/frontend/src/lib/demo-questions.ts` uses TanStack Query with a
5-minute stale window. The chip rail UI itself is L22 scope.

### Streaming observability tile placeholder

New `/admin/observability` tab "Streaming" (always visible to admins;
non-admins are already redirected away). 6 tiles:

- First-token p50 / p95
- Active streams
- Disconnect rate
- Total turn latency p50
- Tool-mix breakdown

Each renders `—` with explanatory body text describing what the value
will mean once L21a's streaming producer (Celery task + Redis Streams)
emits real metrics. The tab also lists the three relevant ADRs (0017,
0018, 0019) inline so an operator landing here pre-flip can read the
wire references immediately.

## What did NOT ship (and why)

- **Live chip rail above the composer** — L22 scope. The library +
  endpoint + hook are all here so L22 can drop the UI in without
  back-and-forth.
- **Streaming tile values** — L21a producer scope. The tiles render
  placeholders.
- **`prompt_template_hash` baked into the demo library** — L25 scope
  (the library version doubles as the comparison anchor for now).

## Verification

```
$ docker compose exec api ruff check . / ruff format --check .   # clean
$ pnpm exec eslint <changed paths> / tsc                         # clean
$ pnpm exec vitest run                                            # 53 / 289 green
$ docker compose exec api pytest                                  # 14 / 14 green (L20.5+L20.6)
$ docker compose exec api python -m app.cli demo-seed             # idempotent, both new courses
$ curl /api/v1/demo-questions                                     # 15 questions, canonical_id locked
```

## Files

**Backend:**
- `apps/backend/app/seeds/rag_from_scratch_demo.py` (new)
- `apps/backend/app/seeds/demo.py` (modified — wire + enrol)
- `apps/backend/app/demo_questions.py` (new — library + invariants)
- `apps/backend/app/api/v1/demo_questions.py` (new — endpoint)
- `apps/backend/app/api/router.py` (modified — register)
- `apps/backend/tests/test_rag_from_scratch_seed.py` (new)
- `apps/backend/tests/test_demo_questions.py` (new — 8 tests)

**Frontend:**
- `apps/frontend/src/lib/api/endpoints.ts` (modified — DemoQuestionsApi + types)
- `apps/frontend/src/lib/query/keys.ts` (modified — qk.demoQuestions)
- `apps/frontend/src/lib/demo-questions.ts` (new — hook)
- `apps/frontend/src/components/admin/observability/StreamingTab.tsx` (new)
- `apps/frontend/src/app/admin/observability/page.tsx` (modified — 4th tab)
- `apps/frontend/tests/demo-questions.test.tsx` (new)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L20.6 row)
- `docs/post-redesign/loop-20.6.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L21-Sec — Security hardening (no streaming yet). Per-IP cap, email-
verify grandfather migration, code-runner subprocess hardening, Llama
3.3 sanitizer, indirect-injection nonce wrapper, IDOR tests,
seed-prod-refusal, Sentry scrubber. Empty `tutor_turn_jobs` table +
reservation columns. **The biggest loop yet** — Codex rescue after.
