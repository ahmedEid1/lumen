# Loop 2 — Goal

**Land Playwright visual-regression baselines so every subsequent redesign loop has CI signal on unintended pixel diffs.**

AUDIT.md §5 flagged "zero visual-regression coverage" as one of the foundation blockers: the existing `screenshots.spec.ts` captures PNGs for the README without diffing, and Loops 3 onwards will start touching component renders. Without baselines, a "while I'm here" tweak to a Skeleton variant could silently shift the catalog cover proportions and no one notices until the next manual sweep.

- **Surface:** new spec at `apps/frontend/tests/e2e/visual-regression.spec.ts`. Reuses the `login()` + `preDismissOnboarding()` helpers from `tests/e2e/helpers/login.ts`. Baselines committed under `tests/e2e/visual-regression.spec.ts-snapshots/`.
- **Persona:** the next CI run on any future redesign loop. The reviewer of any future PR who wants "show me the visible diff this change introduces" without spinning up the app.
- **Binary success criteria:**
  1. 8 routes × 2 themes = 16 baselines captured: `/`, `/courses`, `/login`, `/register` (public); `/dashboard`, `/profile` (student auth); `/studio` (instructor auth); `/admin` (admin auth). Each in both `dark` and `light`.
  2. Spec runs in `chromium` project only (skip `webkit` to control font/scrollbar variance — both browsers don't double the signal, they double the maintenance).
  3. `toHaveScreenshot()` thresholds: `maxDiffPixels: 100`, `threshold: 0.2` (Playwright defaults give zero tolerance which makes anti-aliasing noise red).
  4. Theme is set via `addInitScript` injecting `localStorage["theme"]` before each navigation — matches next-themes' storage shape.
  5. Auth-gated routes use the existing `login()` helper + `preDismissOnboarding()` to dismiss the onboarding tour overlay.
  6. The spec is skipped (`test.skip`) when CI doesn't have access to the seeded data (env-gated by `process.env.SEED_AVAILABLE !== "false"`). In normal local + CI runs against the seeded compose stack, it runs.
  7. **Visual smoke through this loop is exactly Loop 1's no-diff promise:** if the baselines captured here differ from a clean `2049ec8^` checkout, something in Loop 1's duration-literal sweep changed a render — that's the audit signal.
  8. `make test.web` still green (this loop adds e2e, doesn't touch vitest); `pnpm exec playwright test visual-regression.spec.ts` green with the freshly captured baselines.
  9. CI workflow continues to run `e2e` as it does today — the new spec joins automatically since it lives in `tests/e2e/`.

Out of scope:
- Cross-browser baselines (chromium only — webkit baselines doubt-double the maintenance).
- Mobile-viewport baselines (Playwright has no mobile project today; that's a later sweep).
- Storybook-style component-level visual regression. Whole-route screenshots are coarser but match the loop sequence's surface-by-surface cadence.
- Axe-gate growth to fill the 13 blind-spot routes from AUDIT.md §4 #9 — this loop *could* absorb that, but bundling two independent expansions into one loop fights the "one topic per commit" rule. Axe-gate growth ships as Loop 2.5 (or rolled into the surface loop that first touches each blind-spot route).
