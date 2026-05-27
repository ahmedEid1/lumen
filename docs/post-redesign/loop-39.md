# Loop 39 — Wave D/E polish + L35-L38 Codex rescue

**Date:** 2026-05-27
**Status:** Shipped

## Goal

Two threads merged into one bundle per the new cadence:

1. **Wave D/E polish** the plan-v7 roadmap marked as cuttable —
   anti-abuse rate limit on POST `/tutor/turns`, SSE resume +
   poll-fallback hardening.
2. **L35-L38 Codex rescue** — 5 findings (3 P1 on the Sentry
   scrubber, 1 P2 on the baseline runner, 1 P2 on the mobile flip).

## What shipped

### Anti-abuse rate limit on POST /tutor/turns

The legacy POST has carried `@limiter.limit("20/minute")` since
Phase E1; the streaming POST didn't. Now it does. Same per-user/IP
rate as legacy so a switched panel doesn't accidentally exceed
either path's budget.

- `@limiter.limit("20/minute")` on `post_turn`
- `response: Response` added to the handler signature (slowapi
  needs it for the `X-RateLimit-*` header injection — the
  legacy POST handler was the reference pattern).
- 1 new test: 21 sequential POSTs → the 21st should 429.

### SSE resume + poll-fallback hardening (frontend)

`useTutorStream` hook previously gave up on the first stream
error and ignored `trim_detected`. L39 wires three connection
lifecycles:

1. **Transient stream error mid-turn** — retry once with
   `Last-Event-ID` (captured from the snapshot's `lastEventId`)
   so the server replays only the missed events. Second
   consecutive failure → mark `phase: "failed"` (orchestrator is
   likely dead).
2. **`trim_detected` → poll `/status`** — the server's TTL-trim
   signal fires when the SSE buffer dropped events the client
   needed. We poll the status endpoint at 1s intervals for up to
   60s, then synthesise a `turn_complete`/`turn_failed` event so
   the reducer settles cleanly.
3. **Hard errors (401/403/404/503)** — sniffed by message text,
   no retry, snapshot.fail() fires immediately. Avoids burning CI
   on a permanently broken turn.

Logic lifted into `runWithRecovery` + `pollUntilTerminal` outside
the hook body so it's testable without React.

### Sentry scrubber rescue (Codex L35-L38 P1 × 3)

Three real data-leak paths the L38 ship didn't cover:

1. **`extra` and `contexts` dicts** —
   `Sentry.captureException(err, { extra: { prompt, messages } })`
   was an open door. `beforeSendScrub` now calls `scrubMap` on
   both, replacing high-risk keys with the scrubbed marker.
2. **`fetch`/`xhr` breadcrumb `data` payloads** — Sentry's default
   `fetch` integration attaches `data.url` + `data.payload` for
   every request. A breadcrumb to `/api/v1/tutor/turns` was
   carrying the learner's question in clear. Now: if `data.url`
   matches the tutor prefix OR any key is high-risk, the
   `payload`/`body`/`url` fields get zeroed.
3. **Request URL query strings** — `/api/v1/tutor/turns?q=secret`
   left `event.request.url` + `event.request.query_string` in
   place. Both now scrubbed on tutor URLs.

+5 new vitest tests covering each path.

### Baseline runner per-item resilience (Codex L36 P2)

`run_comparison` ran its body in one big `for item in items:` loop
with no try/except. A failure on item 7 of 10 lost the prior 6
pairs. L39 wraps each iteration in a try/except + adds an optional
`on_item_error(item, exc)` callback. Failed items get dropped;
prior pairs come back to the caller.

+1 new test: a flaky `answer_fn` that fails on call 7 returns 4 of
5 pairs cleanly + fires the error callback once.

### What's NOT in this bundle

- **Mobile Sheet vs desktop aside flip race (Codex P2).** Crossing
  the `lg` breakpoint during a streaming turn unmounts the
  TutorPanel + restarts SSE. Fix needs to lift `currentTurnId`
  state above the layout split or persist it externally —
  architectural, separate loop.
- **Catalog v2, studio polish, dashboard refresh.** Vague items in
  the queue; the security/runtime fixes here were higher-leverage.

## Local-first gates (all green)

- `ruff check .` ✓
- `ruff format --check .` ✓
- 51 streaming + tutor + baseline + llm_stream backend tests pass
- `pnpm tsc --noEmit` ✓
- `pnpm vitest sentry-scrubber.test.ts` 11 pass (was 6, +5)
- `pnpm vitest tutor-panel.test.tsx` 3 pass

## Verification on prod (post-deploy)

- `/api/v1/runtime-flags` should still report `tutor_streaming: true`
- 21st POST to `/api/v1/tutor/turns` from the same identity in a
  60s window should 429 (anti-abuse gate)
- Sentry scrubber rescue only manifests once a DSN is wired (still
  operator-allocated) — but the test suite gates the contract
