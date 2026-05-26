# Loop-7 follow-up — Tailwind 4 `max-w-*` collision hotfix

Date: 2026-05-26
Triggering commit (the bug): `2049ec8` (Loop 1 — token foundation, 2026-05-26 ~07:30)
Detection commit: `45f1511` (Loop 9 prod deploy, 2026-05-26 ~10:00) — found during the user-requested "visual review of the deployed" pass
Fix commit: pending (this loop)

## Symptom

The home hero (`apps/frontend/src/app/home-view.tsx` `<Hero>`) renders "Take a path. Become it." one word per line on a 1280px viewport. The `<div class="max-w-3xl">` wrapper around the h1 has a computed `max-width` of **96 px**, not the expected 48 rem (768 px). Same regression affects every other site that uses `max-w-xl`, `max-w-2xl`, `max-w-3xl` etc. — the catalog subtitle "Browse what instructors..." renders one word per line for the same reason.

Forensic capture via Playwright (`window.getComputedStyle` on the offending `<div>`):

```json
{
  "viewport": { "w": 1280, "h": 720 },
  "h1Parent": {
    "className": "max-w-3xl",
    "offsetWidth": 96,
    "computedMaxW": "96px",
    "computedW": "96px"
  }
}
```

Expected: 768 px.

## Root cause

Loop 1 (`2049ec8`) added a named-spacing scale to `@theme inline`:

```css
@theme inline {
  /* Spacing scale aliases — Tailwind reads --spacing-* to extend
     the p-/m-/gap- utility set. After this, `p-md` / `gap-lg` /
     `m-xs` resolve to the named tokens defined in :root. */
  --spacing-xs: 0.5rem;
  --spacing-sm: 1rem;
  --spacing-md: 1.5rem;
  --spacing-lg: 2rem;
  --spacing-xl: 3rem;
  --spacing-2xl: 4rem;
  --spacing-3xl: 6rem;
}
```

**The comment's premise was wrong.** Tailwind 4 reads the `--spacing-*` namespace for far more than just `p-*`/`m-*`/`gap-*` utilities — it also drives `max-width`, `min-width`, and `width` utilities like `max-w-3xl`, `min-w-md`, `w-xl`. So `--spacing-3xl: 6rem` shadowed Tailwind's default `max-w-3xl: 48rem` and re-resolved it to `max-w-3xl: 6rem` (= 96 px). Loop-1's spec brainstorm assumed `--spacing-*` was scoped to the spacing utilities; it isn't.

## Detection

The bug was in prod since Loop 1's deploy approval (~08:00). It survived loops 2, 3, 4, 5, 6, 7, 8, 9 because:

1. The Phase 0 audit agents reviewed *code*, not rendered output. They never opened the running app.
2. The vitest unit suite tests primitive behaviour, not page layout.
3. Playwright VR baselines captured the broken state and treated it as the new normal — Loop 2's first capture was already-broken, so subsequent re-runs matched the broken baseline.
4. No per-loop visual review of the live deploy. The post-deploy ritual was `curl /api/v1/health/ready` (a JSON check), nothing visual.

Caught on Loop 9 because the user added "have also visual review of the deployed, every time you review" to the post-deploy ritual. The walkthrough capture made the broken layout obvious.

## Fix

Remove the `--spacing-*` aliases from `@theme inline`. Keep `--space-*` declarations in `:root` (consumers can use `var(--space-md)` directly via Tailwind arbitrary values: `p-[var(--space-md)]`, `gap-[var(--space-lg)]`, etc.).

Diff (`apps/frontend/src/styles/globals.css`):

```diff
@theme inline {
   /* … other entries unchanged … */

-  /* Spacing scale aliases — Tailwind reads --spacing-* to extend the
-     p-/m-/gap- utility set. After this, `p-md` / `gap-lg` / `m-xs`
-     resolve to the named tokens defined in :root. The existing
-     Tailwind 4px scale (`p-2` = 8px etc.) keeps working alongside. */
-  --spacing-xs: 0.5rem;
-  --spacing-sm: 1rem;
-  --spacing-md: 1.5rem;
-  --spacing-lg: 2rem;
-  --spacing-xl: 3rem;
-  --spacing-2xl: 4rem;
-  --spacing-3xl: 6rem;
+  /* Spacing aliases REMOVED in the loop-7-followup hotfix.
+     Tailwind 4 reads `--spacing-*` for max-w/min-w/w utilities
+     too — so `--spacing-3xl: 6rem` overrode `max-w-3xl` to 96px.
+     Consumers that want the named scale use `var(--space-md)`
+     directly via arbitrary Tailwind values. */
 }
```

Regression test update (`apps/frontend/tests/tokens-foundation.test.ts`):

```diff
-it("aliases the spacing scale for `p-md` / `gap-lg` etc.", () => {
-  // assert each --spacing-* exists in @theme
+it("does NOT alias the spacing scale in @theme (avoids max-w-* collision)", () => {
+  // assert each --spacing-* is ABSENT from @theme as a real declaration
 });
```

## Verification

After the fix, the same Playwright probe shows:

```json
{
  "h1Parent": {
    "className": "max-w-3xl",
    "offsetWidth": 768,
    "computedMaxW": "768px",
    "computedW": "768px"
  }
}
```

768 px ✓. The home hero now renders "Take a path. Become it." on two lines (the muted `<span>` wraps cleanly). Catalog subtitle also reads on 1–2 lines.

`make test.web`: 37 files / 202 tests passed.

## Lessons + memory updates

- **Visual review is non-negotiable post-deploy.** This bug shipped through 8 deploy gates because the post-deploy check was JSON-only. The user's rule "have also visual review of the deployed, every time you review" is now in `active-redesign.md` and codified in `tests/e2e/prod-visual-check.spec.ts`.
- **`--spacing-*` namespace is reserved in Tailwind 4.** Any future named-scale work for spacing should go through component-scoped CSS variables (e.g. `--workbench-space-*`) that DON'T collide with Tailwind's utility derivation. Or use the `@utility` syntax for custom named utilities.
- **VR baselines are not visual review.** Capturing PNGs against a broken page produces a "this is what the page looks like" baseline that survives because *nothing about it changes loop over loop*. The baseline reproduces the bug indefinitely. Visual review = a human (or Codex) actually looking at the page against the design intent.

## What remained out of scope of this hotfix

- **The Codex visual review attempt.** I dispatched the codex-reviewer agent to do an independent visual pass; it returned with `codex review --uncommitted [PROMPT]` rejection in CLI v0.133.0 (CLI grammar regression). The agent recommended an alternative: a CLAUDE vision task using the Read tool on PNGs + design docs. That alternative IS what I just did (above). For Codex as an independent reviewer, the integration needs upgrading or routing through a different mechanism. Tracked as a separate follow-up.
- **The `--space-*` :root declarations.** Kept as-is. They're harmless (no Tailwind utility derivation happens from `--space-*`, only from `--spacing-*`), and they let consumer code use `var(--space-md)` in arbitrary values. Removing them would just churn comment text for no gain.
