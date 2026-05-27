# Loop 22 — chip rail + "Tools used" reframe + RTL leak fix

**Date:** 2026-05-27
**Scope:** Demo-runway UI polish on top of L21a/b streaming spine.

## What shipped

### Demo-question chip rail

`apps/frontend/src/components/tutor/demo-question-chip-rail.tsx`
(new). Reads the L20.6 library via `useDemoQuestions(courseSlug)`.
Renders above the tutor composer **only** when the conversation is
empty. Tap a chip → fills the draft + auto-sends.

Visual posture:
- Header: small mono cartouche `Suggested questions` + Sparkles icon.
- Chips: bordered pills; canonical question gets the lime-tinted
  `border-primary/40 bg-primary/10` variant (the only chip that visually
  pops, signaling "this is the one the screencap captures").
- Truncates prompts >64 chars with full-text in `title=""` for a11y.
- `aria-label` on the canonical chip reads "Try the canonical demo
  question" so a screen-reader user knows which one is the screencap
  target.

Mounted in BOTH `StreamingTutorPanel` (L21b) and `LegacyTutorPanel`
(the renamed pre-L21b implementation) — single component, two call
sites. Both panels grew an optional `courseSlug` prop that flows
through to the chip rail.

### "Tools used" label reframe

i18n keys at `tutor.agentTrace.*` rewritten:

| Key | Before | After |
|---|---|---|
| `title` | Agent thinking | Tools used |
| `show` | Show me how you got this | Show how the tutor got there |
| `hide` | Hide reasoning | Hide tools used |

Per plan-v7 §L22 wording — recruiters parse "Tools used" faster than
"Agent steps" or "Agent thinking." Arabic translations updated to
match.

### RTL leak fix

`apps/frontend/src/app/studio/draft/[courseId]/components/draft-trace-timeline.tsx:94`
— `text-left` → `text-start`. AUDIT §4 had flagged
`agent-reasoning-panel.tsx:117` originally; that one was already
fixed in the redesign Loop 17. The studio draft-trace-timeline
button was the last surviving instance of the same class of leak.

## Tests

| Surface | Tests |
|---|---|
| `DemoQuestionChipRail` (canonical-first + onPick) | 2 |
| Existing parser / UA / runtime-flags / hook suites | all green |
| **L22 total** | **+2 new** |
| Frontend suite | 56 files / 305 tests green |

Backend untouched.

## What did NOT ship

- Real agent-step pending/completed states with per-row latency
  badges — those live alongside the L22-followup that wires the
  streaming events into the existing `AgentReasoningPanel`. The
  chip rail + label reframe + RTL fix are independently shippable;
  the panel rebuild is staged separately.

## Verification

```
$ pnpm exec eslint src/components/tutor src/lib/i18n         # clean
$ pnpm exec tsc --noEmit --incremental false                  # clean
$ pnpm exec vitest run                                         # 56 / 305 green
```

## Files

**Frontend new:**
- `apps/frontend/src/components/tutor/demo-question-chip-rail.tsx`
- `apps/frontend/tests/demo-question-chip-rail.test.tsx`

**Frontend modified:**
- `apps/frontend/src/components/tutor/tutor-panel.tsx`
  (Legacy/Streaming both consume the chip rail; new `courseSlug` prop)
- `apps/frontend/src/components/tutor/streaming-tutor-panel.tsx`
  (same — chip rail above composer + handleSend accepts override)
- `apps/frontend/src/lib/i18n/messages/en.ts`
  (`tutor.agentTrace.*` reframed + new `tutor.suggested.*` keys)
- `apps/frontend/src/lib/i18n/messages/ar.ts` (same)
- `apps/frontend/src/app/studio/draft/[courseId]/components/draft-trace-timeline.tsx`
  (RTL: `text-left` → `text-start`)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L22 row)
- `docs/post-redesign/loop-22.md` (this file)
- `CHANGELOG.md` (modified)

## Codex rescue

L21a + L21b + L22 = 3 loops since the L21-Sec rescue. Codex pass runs
after L22's CI ships. Findings will be addressed in-loop before L23
starts.
