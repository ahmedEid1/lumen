# Loop 20.5 — TS course + `/demo` route + runtime-flags + ADRs 17/18/19

**Date:** 2026-05-27
**Scope:** Demo runway for the L21-Sec → L21a → L21b streaming work

## What shipped

### TypeScript Generics & Variance — new demo course

`apps/backend/app/seeds/ts_variance_demo.py` (new, ~310 LoC). 4
modules / 8 lessons covering:

| Module | Lessons |
|---|---|
| Generics 101 | Why generics exist · Constraints with `extends` · quiz |
| Variance | What variance means · The canonical `Type 'string' is not assignable to type 'T'` error · quiz |
| Conditional + mapped types | `T extends U ? X : Y` · `keyof`, Pick, Omit, Partial |
| Template literals + capstone | Template literal types · Type-safe API client |

Authored deliberately citation-rich and chunk-aligned so the L21 RAG
tutor has ≥3 specific lesson IDs to ground the canonical demo answer
in. Wired into `app/seeds/demo.py::run()` after the other 3 demo
courses; the demo student is also enrolled so `/demo` lands on an
enrolled state without bouncing back to the catalog.

**Idempotency check:** verified — re-running `python -m app.cli
demo-seed` outputs the new line without duplicating any rows. Backend
test `test_ts_variance_seed_returns_existing_course_when_called_twice`
locks this in.

### `/demo` route — one-click demo deep-link

`apps/frontend/src/app/demo/page.tsx` (new). Server-side redirect
(via `redirect()` from `next/navigation`) to:

```
/learn/typescript-variance
  ?tutor=open
  &q=I+keep+getting+%60Type+%27string%27+is+not+assignable+to+type+%27T%27%60+on+this+function+%E2%80%94+here%27s+my+code%2C+why+does+this+happen+and+how+do+I+fix+it%3F
  &lesson=canonical-error
```

The `/learn/[slug]` page now reads three new search params:

- `tutor=open` — pre-opens the tutor panel on mount.
- `q=<question>` — pre-fills the composer textarea via the new
  `initialDraft` prop on `TutorPanel`.
- `lesson=<title-hint>` — case-insensitive substring match on lesson
  titles, picks the first match; falls back to `pickResumeLessonId` if
  no hint or no match.

Anonymous visitors still hit `/login?next=…` via the existing learn-page
auth gate. The two-step flow (sign in with `demo@lumen.test` →
auto-redirected back to `/demo` → tutor open with question prefilled)
is documented in the README's demo-creds block.

Verified live against `localhost:3000/demo` — the dev-mode hybrid (307
template + meta-refresh) lands on the correct URL with all three
params intact.

### Runtime-flags endpoint + frontend hook

`GET /api/v1/runtime-flags` — anon-readable, returns
`{ tutor_streaming: bool }`. Backed by
`Settings.feature_tutor_streaming` (defaults to `False`); L21-Sec will
add a Redis-backed override layer so an admin can flip without a
redeploy.

`useRuntimeFlags()` hook in `apps/frontend/src/lib/runtime-flags.ts`
uses TanStack Query with a 60 s stale window + refetch-on-focus.
`DEFAULT_FLAGS = { tutor_streaming: false }` is returned during the
in-flight period so a page that branches on the flag doesn't
accidentally light up the streaming UI between mount and first
response.

### ADRs

| ADR | Title |
|---|---|
| 0017 | Celery worker pool — prefork + concurrency=4, with `asyncio.run()` inside the task |
| 0018 | Redis Streams (XADD/XREAD), not pub/sub, for SSE tutor replay |
| 0019 | Atomic phase fence + `after_commit` Celery enqueue for tutor turns |

All three drafted in `Proposed` status. Accepted status is gated on
L21a landing the streaming task implementation that the ADRs describe.
The text encodes plan-v7's V7-F1/F2/F3/F4/F6 fixes so a future reader
gets the rationale without having to dig through `/tmp/elp-planning`.

## What did NOT ship (and why)

- **Live demo-question chip rail** — that's L22 scope. /demo prefills
  one question; the chip rail for additional curated questions lands
  with `defaultExpanded={true}` on agent traces.
- **Redis override layer for runtime-flags** — L21-Sec. The wire shape
  is locked here so the frontend can consume it without redeploying.
- **`tutor_streaming=true` default** — stays OFF until L21b's flag-flip
  PR. Until then the existing non-streaming POST path is canonical.

## Verification

```
$ pnpm exec eslint <changed paths>                   # clean
$ pnpm exec tsc --noEmit --incremental false         # clean
$ pnpm exec vitest run                               # 52 / 288 green (+1 file / +2 tests)
$ docker compose exec api pytest tests/test_runtime_flags.py \
      tests/test_ts_variance_demo_seed.py -v          # 4 / 4 green
$ docker compose exec api python -m app.cli demo-seed # idempotent re-apply OK
$ curl /api/v1/runtime-flags                          # {"tutor_streaming":false}
$ curl /demo                                          # 307 → /learn/typescript-variance?…
```

## Files

**Backend:**
- `apps/backend/app/seeds/ts_variance_demo.py` (new — 310 LoC course)
- `apps/backend/app/seeds/demo.py` (modified — wire + enrol demo learner)
- `apps/backend/app/api/v1/runtime_flags.py` (new)
- `apps/backend/app/api/router.py` (modified — register runtime_flags router)
- `apps/backend/app/core/config.py` (modified — `feature_tutor_streaming: bool`)
- `apps/backend/tests/test_runtime_flags.py` (new)
- `apps/backend/tests/test_ts_variance_demo_seed.py` (new)

**Frontend:**
- `apps/frontend/src/app/demo/page.tsx` (new)
- `apps/frontend/src/app/learn/[slug]/page.tsx` (modified — read tutor + q + lesson params)
- `apps/frontend/src/components/tutor/tutor-panel.tsx` (modified — `initialDraft` prop)
- `apps/frontend/src/lib/api/endpoints.ts` (modified — `RuntimeFlagsApi` + `RuntimeFlags`)
- `apps/frontend/src/lib/query/keys.ts` (modified — `qk.runtimeFlags`)
- `apps/frontend/src/lib/runtime-flags.ts` (new)
- `apps/frontend/tests/runtime-flags.test.tsx` (new)

**Docs:**
- `docs/adr/0017-celery-prefork-asyncio-in-task.md` (new)
- `docs/adr/0018-redis-streams-for-sse-replay.md` (new)
- `docs/adr/0019-atomic-phase-fence-and-after-commit-enqueue.md` (new)
- `docs/post-redesign/STATUS.md` (modified — add L20.5 row)
- `docs/post-redesign/loop-20.5.md` (this file)
- `CHANGELOG.md` (modified — Unreleased entry)

## Next loop

L20.6 — RAG-from-scratch course + 15-question curated demo library
(canonical Q is the TS variance error from this loop) + observability
tile prep for L21.
