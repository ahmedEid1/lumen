# Loop 32 — pgvector retrieval wiring in streaming orchestrator

**Date:** 2026-05-27
**Status:** Shipped

## Goal

Replace the noop retriever stub in `tutor_orchestrator_stream.py` with
a real lesson-chunk lookup so the streaming demo actually grounds
answers in course content. This is the first deferred follow-up on
plan-v7 §V7-F12 (RAG inside streaming) — promised at L21a, blocked on
the L31-followup AsyncOpenAI integration landing first.

## What shipped

### Schema (Alembic 0028)

`tutor_turn_jobs` gains two nullable columns so the Celery task can
read the course context + the actual question without a second
round-trip to the POST body:

- `course_id` (FK → `courses.id`, `ON DELETE SET NULL`)
- `user_message` (text, nullable for backfill compat — the existing
  empty table makes this safe)

### POST `/api/v1/tutor/turns`

`NewTurnIn` accepts a new optional `course_slug: str | None`. When
set, the handler resolves the slug → `course_id` via a single
`SELECT id FROM courses WHERE slug = … AND deleted_at IS NULL` and
persists both the resolved id + the user message text on the row.

An unknown slug returns 404 (clean error surface for typos in the
URL bar on `/learn/<slug>`); no slug is fine (degraded synth-only
mode).

### Celery task `tutor.run_turn.v1`

After the atomic phase fence, the task now reads `course_id` +
`user_message` from the claimed row. When both are set, it opens a
second session and runs `tutor_subagents.retriever.run(...)` —
which itself calls `find_relevant_chunks(audit=True)` so the admin
retrieval-audits surface gets a real trace. Latency is captured via
`time.monotonic()` deltas and passed through to the orchestrator.

Retrieval is best-effort: any exception in the retrieval block is
suppressed and the orchestrator runs with `retrieved_chunks=None`.
Better to ship a degraded answer than to fail the whole turn over a
pgvector flake.

### Orchestrator `orchestrate_stream(...)`

Signature gains `retrieved_chunks: list[RetrieverChunk] | None` +
`retrieval_latency_ms: int | None`. The orchestrator stays a pure
async generator — no DB session — because retrieval happens upstream.

Three behaviours based on what the task hands in:

1. **Chunks present** — `tool_call_result.summary` reads `"found N
   chunk(s) across M lesson(s)"`, latency is the real measured
   value, `planner_start.route` is `"retriever+synth"`. The synth
   SYSTEM message gets the `_GROUNDING_INSTRUCTION` block — an
   explicit `[L:<lesson_id>]` citation contract + the actual lesson
   excerpts (one block per chunk, with `lesson_id` and title).
2. **No chunks, no `course_id`** — summary reads `"no course
   context"`, route is `"synth-only"`. No citation contract in the
   system prompt (so the model can't fabricate citation ids).
3. **No chunks, `course_id` set** — summary reads `"no relevant
   content in this course"`, distinguishing "we tried + found
   nothing" from "we never tried".

### Frontend `StreamingTutorPanel`

`postTurn()` signature widened to accept `courseSlug: string | null`.
The prop was already in `StreamingTutorPanelProps` (the L22 chip-rail
needed it). It now also threads through to the POST body as
`course_slug`.

### Tests

+7 backend tests across two files:

- `tests/test_tutor_streaming_orchestrator.py` — 5 new tests:
  - "no chunks, no course_id" summary reads "no course context"
  - "no chunks, course_id set" summary reads "no relevant content"
  - With chunks: summary carries real counts + latency, route flips
  - With chunks: synth SYSTEM message carries `[L:<lesson_id>]`
    contract + `[L:<actual_id>]` handles + excerpt bodies
  - Without chunks: synth SYSTEM message OMITS the citation contract
- `tests/test_tutor_streaming_endpoints.py` — 2 new tests:
  - POST with known `course_slug` stores resolved `course_id` +
    `user_message` on the row
  - POST with unknown slug → 404 (not 500)

Total backend suite passing: 711 → 718.

## What's still deferred

- **Citation rendering in the frontend** — the model now emits
  `[L:<id>]` tokens, but the streaming-tutor renderer just shows them
  verbatim. A small follow-up will swap them for inline lesson
  links. Cosmetic; not blocking the demo.
- **Citation-extractor for the eval suite** — a small parser that
  finds `[L:<id>]` tokens in answers + asserts they're in the
  retrieved set. Belongs to the L36 baseline-runs loop.

## Ops sequencing notes

The `flip-flag.yml` infra workflow shipped just before L32. Its
first run (against `FEATURE_TUTOR_STREAMING=true`) **passed the env
edit but failed the smoke test** — `docker compose restart` does
NOT re-read `--env-file`, so the new flag value wasn't picked up by
the running container. Fixed in the same loop: workflow now uses
`up -d --no-deps` (full recreate) + 12×10s smoke budget (was 5×6s,
too tight for a Graviton cold start).

The env edit on prod DID land — the L32 deploy itself will recreate
the api container via the regular `deploy.yml` path, picking up
`FEATURE_TUTOR_STREAMING=true` automatically.
