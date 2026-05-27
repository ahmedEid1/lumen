# Loop 21b — Frontend streaming + flag-flip

**Date:** 2026-05-27
**Scope:** Frontend SSE renderer + the flag-flip wire shape. Code
ships flag-OFF by default; the prod env override
(`FEATURE_TUTOR_STREAMING=true`) is the actual flip and is documented
in this ledger.

## What shipped

### Foundation

- **`apps/frontend/src/lib/tutor/sse-parser.ts`** — WHATWG-spec-compliant
  parser. Handles multi-line `data`, CRLF/LF/CR terminators,
  mid-chunk-boundary splits, comment lines (`:`), missing colon, the
  spec's single-leading-space strip.
- **`apps/frontend/src/lib/tutor/sse-client.ts`** — fetch-based SSE
  client (not native `EventSource` — we need custom headers for the
  Bearer token). `openSseStream({url, token, lastEventId, signal,
  onEvent, onError})` opens a streaming response, runs the parser
  over each chunk, fires `onEvent` per parsed frame.
- **`apps/frontend/src/lib/tutor/supports-streaming.ts`** — feature
  detect + iOS Safari 15.0–15.3 UA sniff. Apple shipped the API
  surface in 15.0 but the implementation only streams from 15.4 on;
  feature-detect alone is a false positive.
- **`apps/frontend/src/lib/tutor/use-tutor-stream.ts`** — the React
  hook. `useTutorStream(turnId)` opens the SSE connection on mount,
  reduces each event into a snapshot via `useSyncExternalStore` so
  re-renders only fire when state actually changes. Snapshot shape:
  `{phase, tools[], text, error, turnCompleteData, lastEventId}`.

### UI integration

- **`apps/frontend/src/components/tutor/streaming-tutor-panel.tsx`** —
  new component. POSTs to `/api/v1/tutor/turns`, subscribes via the
  hook, renders tools list + accumulating text + cursor animation
  during the synth phase + `aria-live="polite"` on the text region.
- **`apps/frontend/src/components/tutor/tutor-panel.tsx`** — outer
  `TutorPanel` now branches: if `flags.tutor_streaming &&
  supportsStreaming()` → `<StreamingTutorPanel/>`, else → existing
  `<LegacyTutorPanel/>` (renamed inline). Public API unchanged; call
  sites need no edits.

### Flag flip

The runtime flag (`feature_tutor_streaming`) defaults to `False` in
`app/core/config.py`. The frontend reads it via `useRuntimeFlags()`
(L20.5). To enable streaming in prod:

```env
# .env on the prod AWS host
FEATURE_TUTOR_STREAMING=true
```

Then restart the api container; the `/api/v1/runtime-flags` endpoint
returns `{tutor_streaming: true}` and the frontend mounts the new
panel automatically. **The L21b code lands with the flag OFF** so
the legacy path is still canonical until the operator flips it. This
matches the plan-v7 staged-rollout shape (Sec → a → b → flip).

## Tests

| Surface | Tests | Pass |
|---|---|---|
| `SseParser` (parser edge cases) | 9 | ✓ |
| `supportsStreaming()` (iOS UA sniff) | 5 | ✓ |
| **L21b total** | **+14 new** (parser + UA) | ✓ |
| Frontend suite | 55 files / 303 tests | ✓ |

Reducer tests + StreamingTutorPanel render tests are deferred to a
small L21b-followup — the hook's `useSyncExternalStore` + fetch-based
SSE needs jsdom shims that are noisier than the rest of the suite,
and the integration-level coverage comes naturally with the L22
real-LLM-streaming wire-up.

## What did NOT ship (deferred)

- **Reducer unit tests** — moved to L22 alongside the AsyncOpenAI
  integration so the real-events shape can be tested end-to-end.
- **Reconnect-with-backoff loop** in the hook — the L23 cost-cap-hit
  closing-CTA loop will need it; layered then.
- **Time-gated Stop button** + inactivity-timer STREAM_LOST detection
  — L22.

## Verification

```
$ pnpm exec eslint src/components/tutor src/lib/tutor src/lib/runtime-flags.ts # clean
$ pnpm exec tsc --noEmit --incremental false                                   # clean
$ pnpm exec vitest run                                                          # 55 / 303 green
```

Backend untouched in L21b.

## Files

**Frontend new:**
- `apps/frontend/src/lib/tutor/sse-parser.ts`
- `apps/frontend/src/lib/tutor/sse-client.ts`
- `apps/frontend/src/lib/tutor/supports-streaming.ts`
- `apps/frontend/src/lib/tutor/use-tutor-stream.ts`
- `apps/frontend/src/components/tutor/streaming-tutor-panel.tsx`
- `apps/frontend/tests/sse-parser.test.ts`
- `apps/frontend/tests/supports-streaming.test.ts`

**Frontend modified:**
- `apps/frontend/src/components/tutor/tutor-panel.tsx` (top-level
  branch on `flags.tutor_streaming && supportsStreaming()`; inner
  legacy impl renamed to `LegacyTutorPanel`)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L21b row)
- `docs/post-redesign/loop-21b.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L22 — Live agent-step panel (real values in the streaming "Tools used"
list, not just labels), demo-question chip rail above the composer
(consumes `useDemoQuestions(courseSlug)` from L20.6), RTL leak fix at
agent-reasoning-panel.tsx:117, "Tools used" label reframe. Per the
every-3-loop Codex cadence (post-rescue), L22 is the next rescue
checkpoint.

## Footnote — packaging mishap

Commit `7544c91` was titled "ruff format L21a orchestrator test" but
swept in the L21b foundation files (sse-parser, sse-client,
supports-streaming, use-tutor-stream) because I ran `git add -A`
before the L21b changes were complete. The history is harmless but
the commit message under-describes the diff. L21b's actual
shipping-commit (this loop) ships the rest.
