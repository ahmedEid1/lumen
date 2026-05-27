# Loop 23 — Cost-cap closing CTA

**Date:** 2026-05-27
**Scope:** Replace the generic 503/429 surface on cost-cap errors with
a recruiter-friendly closing CTA. The "approaching daily cap" banner
is deferred until the actual cost-reservation wiring lands (a
follow-up to L21a).

## What shipped

### `<CostCapClosingCta />` component

`apps/frontend/src/components/tutor/cost-cap-closing-cta.tsx` (new).
Renders when a tutor turn fails with one of:

| Error code | Source |
|---|---|
| `llm.budget_exceeded` | Phase H1 — already shipped |
| `tutor.user_cap` / `tutor.ip_cap` / `tutor.global_cap` | L21-Sec Lua scripts (callers land with the L21a follow-up) |

Visual posture:
- Bordered `surface` card; `role="alert"`.
- Wallet icon + "Demo budget reached" cartouche.
- Locked copy explaining the demo runs on a real LLM budget (cost
  honesty is the message — this is Ahmed's portfolio, not a SaaS).
- Optional reset-timer line `Resets in ~Nh` rendered only when a
  future `resetAt` is supplied.
- Two CTAs: `<a mailto:...>` (always) + `<a target="_blank">` to a
  Calendly URL (when provided).

### `isCostCapError(err)` helper

Same module exports a type-checker that introspects an error's
`code` field (the canonical shape from `endpoints.ts` thrown errors)
*and* falls back to matching the snake-case identifier against
`Error.message` — defensive belt-and-braces because the API client's
error wrapping currently surfaces the message string rather than the
structured code, and a future client-library upgrade might switch
that around.

### Panel integration

Both `LegacyTutorPanel` and `StreamingTutorPanel` now branch on
`isCostCapError`:

- **Legacy panel**: `sendMut.onError` suppresses the toast on
  cost-cap errors (one focused surface, not two). The chip rail is
  replaced with the closing CTA on cost-cap POST failures.
- **Streaming panel**: same toast suppression on `sendMut.onError`;
  the post-time CTA renders above the messages area; the stream-time
  `stream.phase === "failed"` branch also routes to the CTA when
  `isCostCapError(stream.error)` is true.

## What did NOT ship

- **"Approaching daily cap" banner** at >80% spend — depends on the
  backend cost-reservation wiring (L21a follow-up). Today nothing
  reserves cost on `POST /tutor/turns` (`reserved_cost_usd=0` per the
  L21a deferred scope), so the banner would render against zero
  forever. Plumbing lands alongside the real-LLM-streaming work.
- **Calendly link** — passed as an optional prop; the call site can
  set it once Ahmed has a public Calendly. Today defaults to the
  contact-email-only path.

## Tests

| Surface | Tests |
|---|---|
| `isCostCapError` (code + message fallbacks + non-match) | 3 |
| `<CostCapClosingCta>` (copy, timer, optional Calendly) | 4 |
| **L23 total** | **+7 new** |
| Frontend suite | 57 files / 312 tests green |

Backend untouched.

## Verification

```
$ pnpm exec eslint src/components/tutor src/lib/i18n  # clean
$ pnpm exec tsc --noEmit --incremental false           # clean
$ pnpm exec vitest run                                  # 57 / 312 green
```

## Files

**Frontend new:**
- `apps/frontend/src/components/tutor/cost-cap-closing-cta.tsx`
- `apps/frontend/tests/cost-cap-closing-cta.test.tsx`

**Frontend modified:**
- `apps/frontend/src/components/tutor/tutor-panel.tsx` (Legacy
  panel: suppress toast on cost-cap; render CTA on cost-cap POST
  failure)
- `apps/frontend/src/components/tutor/streaming-tutor-panel.tsx`
  (same; plus stream.phase==="failed" routes to CTA when the error
  is cost-cap)
- `apps/frontend/src/lib/i18n/messages/en.ts` (+6 keys under
  `tutor.costCap.*`)
- `apps/frontend/src/lib/i18n/messages/ar.ts` (+6 keys)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L23 row)
- `docs/post-redesign/loop-23.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L24 — Mobile/tablet agentic pass (closes AUDIT §7 row 16) +
canonical mobile screenshot (390×844, tutor open, mid-stream, tool
rows above fold) → README hero + case-study lead + og:image. The
mobile pass is the last UX-quality loop before L25's eval
instrumentation.
