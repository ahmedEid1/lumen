# Loop 7 — Options

The single design call here is the **light-mode surface ramp**. The Sonner unpinning + the deferred-baseline capture are mechanical. The brainstorm is for the ramp shape.

## Decision 1 — `.light` surface + border deltas

Current state (globals.css:54-86):
```
--background: 60 9% 98%;     /* #FAFAFA — off-white */
--card:       0 0% 100%;     /* #FFFFFF — white */
--muted:      60 5% 96%;     /* #F4F4F2 — slightly dimmer than bg */
--border:     60 5% 90%;     /* #E5E5E2 — barely visible on white card */
--surface-1:  0 0% 100%;
--surface-2:  60 5% 96%;
--surface-3:  60 5% 92%;     /* #ECECE8 — almost no delta from surface-2 */
```

Deltas are 2-4% lightness. On a 1280px-wide page, the eye reads this as one undifferentiated wash. The audit calls it three steps too close to read as elevation.

### Option A — Linear-light-faithful (warm whites + visible borders)

```
--background: 60 9% 98%;     /* #FAFAFA */
--card:       0 0% 100%;     /* #FFFFFF */
--muted:      60 5% 96%;     /* #F4F4F2 — DIMMER than bg, used for input fields, hover */
--border:     220 6% 88%;    /* #DEDFE0 — visible against white cards */
--surface-1:  0 0% 100%;     /* card-level (same as --card) */
--surface-2:  60 5% 96%;     /* muted-level */
--surface-3:  220 6% 88%;    /* popover-level (matches border) */
```

- **Pros:** Borders become visible. Cards visually lift off bg. Three real elevation layers: bg → card (via border) → popover (via darker surface-3). Closest to Linear / Vercel / Raycast light themes.
- **Cons:** Borders going from #E5E5E2 to #DEDFE0 is a 4-point lightness jump — every bordered surface re-blesses. Lots of binary diff churn.

### Option B — Slate-cool (drop the warm yellow tint)

```
--background: 220 14% 98%;   /* #F9FAFB — neutral off-white */
--card:       0 0% 100%;
--muted:      220 9% 94%;    /* #E5E7EB — neutral light gray */
--border:     220 13% 91%;   /* #E5E7EB — same as muted */
--surface-1:  0 0% 100%;
--surface-2:  220 9% 94%;
--surface-3:  220 13% 88%;
```

- **Pros:** Drops the current `60 9% 98%` warm-yellow tint that doesn't pair well with the cool-grey `--muted-foreground: 213 7% 40%` family. Reads "operator-cold" rather than "operator-warm". Borders visible. Same deltas as Option A.
- **Cons:** A bigger visual departure from the current light theme — re-blesses more aggressively (background changes too, not just borders). Workbench's hue family is currently warm-ish (`60 9%` family for bg, `220 14%` for foreground); this option splits the difference oddly — cool bg, warm-ish primary.

### Option C — Stay warm, just push the deltas

```
--background: 60 9% 98%;     /* #FAFAFA — unchanged */
--card:       0 0% 100%;
--muted:      60 5% 96%;     /* unchanged */
--border:     60 5% 86%;     /* #DBDBD6 — push border darker, keep warm tint */
--surface-1:  0 0% 100%;
--surface-2:  60 5% 96%;
--surface-3:  60 5% 86%;     /* matches border */
```

- **Pros:** Smallest hue change — keeps the warm Workbench identity. Just deepens the border/surface-3 to make elevation visible. Less re-bless churn than B.
- **Cons:** Doesn't address the fact that `--muted-foreground 213 7% 40%` (cool blue-grey) on `--muted 60 5% 96%` (warm) creates a subtle warm-on-cool clash. Light mode would still feel slightly muddy.

## Decision

**Option A.** Reasons:
1. The Linear/Vercel/Raycast comparison is the canonical Workbench design language — Option A is what those products actually ship.
2. Mixing the cool `220 6%` family into `--border` + `--surface-3` (while keeping `60 9% 98%` for bg) is the same "two-family palette" trick the dark mode uses (`220 14%` for surfaces, `72 100%` for the lime accent). Consistency.
3. Option B's slate-cool background departs too far for one loop; if light mode wants a deeper redesign, do that in a future loop with its own brainstorm. Option A is the upgrade that *closes the audit* without a re-think.
4. Re-bless churn from Option A is real but bounded: every bordered surface gets a more visible border, which is the point. The PNG bytes change, the design intent stays.

## Decision 2 — Sonner toast palette under `.light`

The current pin (`<Toaster richColors theme="dark" />`) exists because sonner's default light palette failed axe. Options:

- **Option α — Drop the pin, accept whatever sonner ships in light.** Likely fails axe again.
- **Option β — Drop the pin, override sonner's per-`data-type` colors in globals.css with Workbench tokens** so light + dark both consume our semantic colours.
- **Option γ — Keep the pin, document the trade-off as "intentional", move on.** Cowardly.

**Decision: β.** Adds ~30 lines of CSS to globals.css that target `[data-sonner-toast][data-type="…"]` selectors and override `--normal-bg`, `--normal-text`, `--success-bg`, etc. with our `--success`/`--destructive`/`--warning`/`--info` tokens. Then drop the pin. Net result: sonner reads the active theme, our overrides match each tone's WCAG-passing token from globals.css.

## Decision 3 — Light-mode `--primary` (electric lime)

Already decided in `loop-7-goal.md`: skipping. Keep `--primary: 75 80% 25%` (deep olive) as the AA-safe single token. Don't introduce `--primary-bright`. Light mode reads "operator-deep" not "operator-electric" by design.

## Decision 4 — Re-bless cadence

Light baselines diff intentionally; dark baselines should be unchanged.

- **Approach:** Run the visual-regression suite without `--update-snapshots`. Note which baselines diff. For each diff: visually inspect, confirm it matches the intended redesign (new border colour, new surface-3, new sonner toast palette where visible). Then `--update-snapshots` once with intent and commit.
- **Expected re-bless:** 4 public light + 4 auth-gated light + possibly 2 deferred light = up to 10 PNGs.
- **Expected stable:** All 6 dark baselines (light-mode change doesn't touch dark tokens).
