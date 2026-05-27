# Loop 26 — `/admin/evals` UI: sparkline trend per suite

**Date:** 2026-05-27
**Scope:** Minimal-viable charts upgrade for the admin eval surface.
Recruiters land here from the L27 public `/eval` page if they want
the operator view — a trend signal at a glance is what matters
before per-run drill-downs.

## What shipped

### `<Sparkline />` component

`apps/frontend/src/components/eval/sparkline.tsx` (new). Pure SVG —
no chart library; the Workbench aesthetic favours monochromatic
minimal visuals. 64×16 line with a `<title>` element for
screen-reader spoken-summary.

API:

```tsx
<Sparkline
  data={[{value: 3.85}, {value: 4.10}, ...]}
  range={[0, 5]}                  // default eval-score range
  ariaLabel="Trend over last 8 runs"
/>
```

Values outside the supplied range are clamped (eval scores are
bounded; callers don't normalize themselves). An empty data array
renders the placeholder `——` so the layout doesn't jump.

### SuiteCard sparkline integration

`apps/frontend/src/app/admin/evals/page.tsx` — each suite card now
renders an 8-run trend sparkline to the right of the headline score.
Oldest run on the left, newest on the right; the focus dot sits on
the most recent value.

The `historyBySuite` grouping is computed once at the top of the
page (alongside the existing `latestBySuite`) so each SuiteCard
receives a pre-sliced array.

The sparkline tint uses `text-primary` (lime); the headline number
stays foreground for legibility. The aria-label reads
"Trend over last N runs (oldest left)" so a screen-reader user
gets the orientation.

## Tests

| Surface | Tests | Pass |
|---|---|---|
| `<Sparkline>` (segments, clamping, empty state, a11y, focus dot) | 5 | ✓ |
| **L26 total** | **+5 new** | ✓ |
| Frontend suite | 58 files / 317 tests green | ✓ |

Backend untouched.

## What did NOT ship (deferred to L26-followup or L27)

- **Pass/fail trend chart** as a separate Stacked View — the L26
  sparkline covers the scalar mean; per-axis sparklines (grounding /
  accuracy / style) land alongside the L27 public surface where the
  reader actually consumes them.
- **First-token p50/p95 chart** — needs the streaming-eval harness
  (deferred to the streaming-flag-flip follow-up).
- **Adversarial refusal-rate card** — needs a backend endpoint that
  exposes the latest adversarial run; L25's `app/evals/adversarial.py`
  ships the scorer but no scheduled run / endpoint yet. Lands in
  L27 alongside the public surface.
- **Baseline-comparison bars** — needs real comparison runs. L25
  ships the wire shape (`baseline.py`). Lands when LLM budget is
  allocated.
- **Per-run drill-down side-by-side prompt/response** — already
  exists at `/admin/evals/[suite]/[reportId]` from Phase H2; L26
  doesn't touch it.

## Verification

```
$ pnpm exec eslint src/app/admin/evals src/components/eval   # clean
$ pnpm exec tsc --noEmit --incremental false                  # clean
$ pnpm exec vitest run                                         # 58 / 317 green
```

## Files

**Frontend new:**
- `apps/frontend/src/components/eval/sparkline.tsx`
- `apps/frontend/tests/sparkline.test.tsx`

**Frontend modified:**
- `apps/frontend/src/app/admin/evals/page.tsx` (history grouping +
  sparkline in SuiteCard)

**Docs:**
- `docs/post-redesign/STATUS.md` (modified — L26 row)
- `docs/post-redesign/loop-26.md` (this file)
- `CHANGELOG.md` (modified)

## Next loop

L27 — Public `/eval` surface (read-only, no auth). Top of page = ONE
worked example in full (the canonical demo question + agent answer +
rubric + tool path + cost + first-token). Then aggregate charts
(reusing the L26 sparkline). Adversarial pass-rate shown without
disclosing the prompts. Date stamp + commit hash visible.

Per the every-3-loop Codex rescue cadence: L23 + L24 + L25 + L26 =
4 loops since the last rescue (which fired after L22). One off
schedule — next rescue runs after L27.
