# Loops 35-38 — bundle: mobile Sheet + baseline runner + Anthropic streaming + frontend Sentry

**Date:** 2026-05-27
**Status:** Shipped as one bundle (user directive: 1500-2500 LoC per push)

## Why bundled

Per the local-first workflow update earlier in this session, small
per-loop pushes were burning CI cycles without proportional value.
Four mechanically-independent follow-ups land together: each has
local-first tests green, none depends on the others.

## L35 — Mobile Sheet redo (SSR-safe useMediaQuery)

The L24 mobile bottom-Sheet was reverted at L31 because the Sheet
portals to `document.body` regardless of viewport, so both the
desktop inline `<aside>` and the mobile `<Sheet>` rendered at the
same time → Playwright strict `getByTestId("tutor-panel")` flagged
two matching elements. L35 re-introduces the Sheet but only ONE
panel mounts at a time, gated on a real viewport check.

- New `src/lib/hooks/use-media-query.ts` — `useSyncExternalStore`-
  based hook. Returns `serverFallback` (default `false`) on the
  server + first client render → matches what the server emits →
  no hydration warning. The matchMedia subscription kicks in after
  hydration and the correct branch renders.
- `learn/[slug]/page.tsx` now branches: `isDesktop && tutorOpen`
  renders the inline `<aside>`; `!isDesktop` renders the `<Sheet>`
  with the tutor inside. Only one is ever in the DOM at a time.

## L36 — Baseline runner wire (`run_one_item` + `run_comparison`)

L25 shipped the BaselineScore/BaselinePair primitives + delta math.
L36 adds the actual side-by-side loop:

- `run_one_item(item, *, provider_name, answer_fn, score_fn)` —
  composes the caller's answer + score closures into a
  `BaselineScore`. The closure parameters let tests pin
  deterministic stubs without touching the orchestrator; the
  operator-time invocation passes real closures that drive the
  orchestrator + LLM-as-judge.
- `run_comparison(items, *, primary, baseline, answer_fn, score_fn)`
  runs the dataset against both providers + computes per-item
  deltas. Aggregate via the existing `aggregate_pairs()`.

The actual GPT-4-mini run + promotion to `/eval` is still an
operator step — needs a real OpenAI key allocated. The runner now
exists for that handoff.

## L37 — Anthropic streaming in `llm_stream.py`

The L31-followup wired OpenAI streaming; the Anthropic branch
raised `NotImplementedError`. L37 closes it.

- `_stream_chat_anthropic()` uses the SDK's
  `client.messages.stream(...)` async context manager. The SDK's
  `text_stream` async iterator yields each delta; after iteration
  `get_final_message()` returns the message with usage tokens.
- Same `StreamChunk` contract as the OpenAI path; cost computed by
  the shared `_estimate_cost` pricing helper.
- 2 new tests: `requires_api_key` (clear RuntimeError, no hang) +
  `yields_text_then_terminal_usage` (fake SDK stream context
  manager → assert text + usage payload).

## L38 — Frontend Sentry (`@sentry/nextjs` 8.x)

Backend already had the L21-Sec scrubber + Glitchtip-ready
init; frontend was uninstrumented. L38 mirrors the backend
pattern.

- `pnpm add @sentry/nextjs@^8` → 167 new packages, lockfile
  updated.
- `sentry.client.config.ts`, `sentry.server.config.ts`,
  `sentry.edge.config.ts` — three runtime configs at the project
  root (where `@sentry/nextjs` auto-loads them). DSN comes from
  `NEXT_PUBLIC_SENTRY_DSN` (client) or `SENTRY_DSN` (server/edge).
  When unset, `Sentry.init()` short-circuits → no events, no
  console noise.
- `src/lib/sentry/scrubber.ts` — `beforeSendScrub(event)` mirrors
  the backend's `app.core.sentry_scrubber.before_send`. Scrubs:
  tutor-category breadcrumbs (full wipe), request bodies on
  `/api/v1/tutor/*`, high-risk stacktrace vars (prompt,
  user_message, completion, etc.), exception messages mentioning
  tutor/retriever/synth.
- `next.config.ts` wrapped with `withSentryConfig(config, opts)`.
  Plugin opts: `silent`, `widenClientFileUpload: false`,
  `hideSourceMaps: true`, `disableLogger: true`. Source-map
  upload requires `SENTRY_AUTH_TOKEN` at build time; without it
  the plugin is a no-op wrapper.
- 6 new tests in `tests/sentry-scrubber.test.ts` covering each
  scrubbing path.

**Verified prod build works without a DSN** — `SENTRY_DSN=
NEXT_PUBLIC_SENTRY_DSN= pnpm build` completes cleanly. The
runtime Sentry.init() guards on the env var so a dev/CI build
with no DSN doesn't crash, and the plugin's silent mode keeps
the build output clean.

## Local-first gates (all green)

- `ruff check .` ✓
- `ruff format --check .` ✓
- 52 streaming-tutor + llm_stream + baseline backend tests pass
- `pnpm tsc --noEmit` ✓
- `pnpm vitest tests/sentry-scrubber.test.ts` 6 pass
- `pnpm vitest tests/tutor-panel.test.tsx` 3 pass
- `pnpm build` (no DSN) ✓

## What's NOT in this bundle

- Operator-side: actual sealed eval snapshot promotion to `/eval`.
  Needs real LLM budget + the L36 runner closures wired against
  real providers — an operator task.
- L39 wave D/E polish (anti-abuse, SSE resume, catalog v2, studio
  polish, dashboard refresh) — next bundle.
- L40 final review + visual sweep — closing bundle.
