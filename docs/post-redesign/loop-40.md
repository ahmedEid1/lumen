# Loop 40 — Final Codex rescue + post-redesign arc close

**Date:** 2026-05-27
**Status:** Shipped — closes the L19.5 → L40 post-redesign arc.

## Goal

Two threads:

1. **Codex rescue on L39** — final review surfaced 2 P1 + 3 P2 in the
   newly-shipped anti-abuse + SSE resume + scrubber rescue.
2. **Closing the post-redesign arc** — STATUS + CHANGELOG + memory
   updates so a future session can pick up from a clean handoff.

## Codex L39 findings + fixes

### P1 — Breadcrumb data scrubbing left high-risk keys intact

`hasTutorSignalInData(bc.data)` correctly detected a tutor
breadcrumb but only zeroed the fixed fields `payload`/`body`/`url`.
A breadcrumb shaped `{ data: { prompt: "learner text" } }` still
shipped `prompt` in clear.

**Fix:** walk the entire data dict via the (now-recursive)
`scrubMap` first, then overwrite the conventional fields.

### P1 — `scrubMap` was one-level deep

`contexts.tutor.request.prompt` leaked because `scrubMap` only
checked top-level keys.

**Fix:** recursive walk with `MAX_DEPTH = 5` guard (cyclic refs +
unexpectedly deep payloads can't blow the stack). Arrays are
treated as opaque (no array-element recursion — Sentry doesn't
attach high-risk arrays in practice and the depth cap keeps the
common case fast).

### P2 — `pollUntilTerminal` fetch had no per-request timeout

The outer `signal` only aborts on component teardown. A stuck
`fetch` could block one iteration of the 60s budget indefinitely
— the loop never advances, UI sits in `phase: "trim"` forever.

**Fix:** per-request `AbortController` + `setTimeout(3000)`
chained via a `composeAbort(...)` helper. The fetch races the
3s deadline; on timeout the catch block fires and the loop
moves on.

### P2 — Clean EOF on second SSE retry didn't mark failed

If both `openSseStream` attempts closed cleanly without ever
yielding a terminal event (proxy idle timeout / server-side
close mid-synth), `hadError` stays false and the loop exited
silently. The snapshot lingered in `planning`/`tool`/`synth`
forever.

**Fix:** post-loop guard — if no terminal phase reached, call
`store.fail("tutor.stream_eof")`.

### P2 — `on_item_error` callback swallowed intentional aborts

`contextlib.suppress(Exception)` around the callback defeated
the documented circuit-breaker contract — a callback that raises
to signal "stop the run" (cumulative budget cap, etc.) was
silently dropped.

**Fix:** removed the suppress. Callbacks now propagate. Added
`test_run_comparison_respects_circuit_breaker_callback` to pin
the contract.

## Post-redesign arc summary

23 loops shipped from L19.5 (2026-05-26) through L40 (2026-05-27).
Headline ledger:

- **L19.5-L21-Sec** — founding story + TS Generics course + RAG
  course + security primitives (cost-cap Lua, scrubber, code-runner
  RLIMIT, email-verify grandfather).
- **L21a-L24** — streaming spine. POST/SSE/cancel + Celery atomic
  phase fence + frontend SSE parser + tutor panel + cost-cap CTA +
  mobile pass.
- **L25-L28** — eval substrate. Adversarial probes + baseline
  primitives + sparkline trend + public `/eval` + `/eval/methodology`
  (interview-ready milestone).
- **L29-L31** — landing polish. Animated agent-replay hero + 1300-
  word case study + OG cards across 8 routes + README portfolio +
  shot list.
- **ops/flip-flag** — `flip-flag.yml` workflow (FEATURE_*/LUMEN_*
  whitelist, atomic .env edit, `up -d --no-deps` recreate, 120s
  smoke).
- **L32** — real pgvector retrieval wired into the streaming
  orchestrator + `[L:lesson_id]` citation contract + course-context
  columns + `course_slug` in NewTurnIn.
- **L33** — cost-reserve at POST /tutor/turns + Celery reconciles
  on terminal. 5 settings knobs + 4 AppError classes. Also fixed
  the docker-compose env-anchor that was eating `FEATURE_TUTOR_STREAMING`.
- **L34** — same defences on legacy POST + both paths now write
  `tutor_turn_jobs` rows.
- **L32→L34 rescue** — 5 P1 fixed (cost-bucket prefix mismatch
  with sweep, 404 reservation leak, cancel-pending leak, legacy
  reconcile bypass, legacy post-reserve leak).
- **L35-L38** — bundle. Mobile Sheet (SSR-safe useMediaQuery) +
  baseline runner closures + Anthropic streaming + frontend
  `@sentry/nextjs` + tutor-namespace scrubber.
- **L39** — anti-abuse rate limit + SSE resume hardening + L35-L38
  Codex rescue (3 P1 Sentry + 1 P2 baseline).
- **L40** — final Codex rescue + this memo.

## Streaming demo is live in prod

- `https://lumen.ahmedhobeishy.tech/api/v1/runtime-flags` →
  `{"tutor_streaming": true}`.
- POST `/tutor/turns` reserves cost + concurrency, retrieves
  pgvector chunks, streams real Llama 3.3 70B tokens via Groq,
  reconciles cost on terminal.
- Both legacy and streaming POSTs write to `tutor_turn_jobs` —
  one observability timeline.

## What's still operator-led (not done in code)

These items the user explicitly preserved as MUST-ASK-FIRST,
unchanged in this arc:

- **Repo rename `E-Learning-Platform` → `lumen`** (breaks bookmarks).
- **Distribution drafts going public** — Twitter / LinkedIn /
  Show HN.
- **Canonical demo question lockdown** — after the 10/10 tool-
  sequence eval gate. The eval-gate substrate is in place; the
  actual sealed run + promotion to `/eval` needs a real LLM
  budget.

## Final verification

Local-first gates (pre-push):
- `ruff check` + `ruff format --check` → 295 backend files clean
- 52 backend tests in the touched files pass
- `pnpm tsc --noEmit` clean
- `pnpm vitest run` → **62 files / 342 tests pass** (full suite)

Prod (post-L39):
- `https://lumen.ahmedhobeishy.tech/api/v1/health/live` → `{"status":"ok"}`
- `https://lumen.ahmedhobeishy.tech/api/v1/runtime-flags` →
  `{"tutor_streaming": true}`
