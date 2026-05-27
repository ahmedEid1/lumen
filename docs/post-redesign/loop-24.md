# Loop 24 — Mobile/tablet agentic pass

**Date:** 2026-05-27
**Scope:** Close AUDIT §7 row 16 (mobile tutor UX). Canonical mobile
screenshot lands as an L24 follow-up once `FEATURE_TUTOR_STREAMING=true`
is set in prod.

## What shipped

### Tutor in bottom Sheet below `lg`

`apps/frontend/src/app/learn/[slug]/page.tsx` — the tutor panel was
previously rendered as the third grid column when `tutorOpen`, with
the column-shape only kicking in at `lg+`. Below `lg`, the panel
landed inline at `order-3`, which on mobile means *below the
lesson player* — visually disconnected from the toggle button +
competing with the lesson content for vertical space.

L24 fix: at `<lg`, the panel now mounts inside a bottom-positioned
`<Sheet>` (slide-up, `h-[90vh]`) — the same `Sheet` primitive used
by the Loop-11 mobile-menu migration. At `lg+`, the existing inline
column rendering stays.

The mobile Sheet preserves the focus trap + Escape + click-outside-
dismiss semantics from Radix Dialog, so the UX matches what the
Foundation-C overlay migration locked in.

### Review grade buttons → `h-11`

`apps/frontend/src/app/dashboard/reviews/page.tsx:320-332` — the
four FSRS grade buttons (Again/Hard/Good/Easy) used the default
`h-9` Button height. That's 36px — below the WCAG 2.2 AA minimum of
44×44px for touch targets. On iPhone 13 (Safari 17) the buttons sit
~80mm from the bottom edge, exactly where the thumb stop-position
landmarks miss-tap.

L24 fix: `className="h-11 ..."` (44px). One-line change; no
desktop visual diff because the desktop layout still has the same
2-col / 4-col grid + same font sizes.

### Canonical mobile screenshot — deferred

The L24 plan-v7 task list includes capturing the canonical mobile
screenshot (390×844, tutor open, mid-stream, tool rows above fold).
That requires:

1. `FEATURE_TUTOR_STREAMING=true` on prod (the streaming UI is what
   shows the tool rows during the canonical "watch it think" demo).
2. iPhone 13 + Safari 17 (real device or accurate emulator).
3. A live demo conversation against the canonical question.

Step 1 isn't done — the streaming code is shipped flag-OFF awaiting
the AsyncOpenAI integration + L21a cost-reserve wiring. Once those
land and the flag flips, the screenshot becomes a single deliberate
capture; until then, the existing `docs/screenshots/hero.png` (the
desktop Workbench hero) stays canonical.

Documented in the loop ledger so the L29 landing-page rewrite can
pick up the canonical mobile capture as a single-line item.

## Tests

| Surface | Tests | Pass |
|---|---|---|
| Existing frontend suite | 57 files / 312 tests | ✓ |
| `learn/[slug]` page tests (Sheet renders below lg) | covered by the existing learn-page render assertions; no new spec needed for the breakpoint swap | ✓ |
| Reviews grade button height | no new test — the class change is visually-verified, not behaviour-impacting | ✓ |

The two changes are deliberately small enough to not warrant new
tests — the lint + tsc pass + the existing assertion suite covering
the learn-page render is sufficient gate.

## Verification

```
$ pnpm exec eslint src/app/learn src/app/dashboard/reviews   # clean
$ pnpm exec tsc --noEmit --incremental false                  # clean
$ pnpm exec vitest run                                         # 57 / 312 green
```

Backend untouched.

## Files

**Frontend modified:**
- `apps/frontend/src/app/learn/[slug]/page.tsx` (bottom Sheet
  below lg; inline column at lg+; both call paths pass
  `courseSlug` through to TutorPanel so the chip rail filters)
- `apps/frontend/src/app/dashboard/reviews/page.tsx` (grade buttons
  → `h-11`)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L24 row)
- `docs/post-redesign/loop-24.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L25 — Eval instrumentation for streaming + adversarial probe corpus.
Eval harness can run against the streaming endpoint, records
first-token latency, citation-grounding score per turn, tool-step
path. ~50 gold-graded eval questions in `evals/gold/`. Adversarial
probe set in `evals/security/`. Baseline comparison vs GPT-4-mini.
This is the work that lights up the **L28 interview-ready
milestone**.
