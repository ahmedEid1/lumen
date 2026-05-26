# Loop 2 — Options

## Option A — One spec, parametrised per route × theme, baselines committed (chromium only)

```ts
const ROUTES: { name: string; path: string; auth?: SeedRole }[] = [
  { name: "home", path: "/" },
  { name: "catalog", path: "/courses" },
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
  { name: "dashboard", path: "/dashboard", auth: "student" },
  { name: "profile", path: "/profile", auth: "student" },
  { name: "studio", path: "/studio", auth: "teacher" },
  { name: "admin", path: "/admin", auth: "admin" },
];

for (const route of ROUTES) {
  for (const theme of ["dark", "light"] as const) {
    test(`${route.name} (${theme})`, async ({ page, browserName }) => {
      test.skip(browserName !== "chromium", "baseline pinned to chromium");
      await page.addInitScript((t) => localStorage.setItem("theme", t), theme);
      if (route.auth) await login(page, route.auth);
      await page.goto(route.path);
      await page.waitForLoadState("networkidle");
      await expect(page).toHaveScreenshot(`${route.name}-${theme}.png`, {
        fullPage: true,
        maxDiffPixels: 100,
      });
    });
  }
}
```

- **Pros:** one file, one matrix, one source of truth. Easy to add a new route — append to the array. The skip-on-non-chromium keeps webkit's project alive for the *behaviour* specs without blessing it for visual diffs. Baselines are PNGs in the repo, so a reviewer can `git show` the file and see the actual pixels of a change.
- **Cons:** 16 PNGs at ~150KB each = ~2.4MB committed (every redesign-touching commit may also re-bless the bytes, growing history). Animation timing — even with `prefers-reduced-motion: reduce` cycling through the global CSS rule, hover transitions on first paint can land at variable progress. Mitigation: `page.waitForLoadState("networkidle")` + explicit `await page.waitForTimeout(200)` settle window.

## Option B — Playwright Visual Comparison + Chromatic (or Percy) external service

```yaml
# CI step
- run: pnpm exec chromatic --auto-accept-changes
```

- **Pros:** fancy review UI (commit-by-commit visual diff browser, accept-as-baseline button per change, parallel browser shots). External storage so the repo doesn't carry the PNGs.
- **Cons:** external dependency / monthly cost (Chromatic free tier is 5000 snapshots/mo which we'd burn through fast given the loop cadence). Requires CI secrets (`CHROMATIC_PROJECT_TOKEN`). Adds a third-party between us and shipping. Migration cost from `toHaveScreenshot` later (if we change our minds) is non-trivial.
- **Why rejected:** the project is solo-operator and free-tier; pay-per-snapshot isn't a fit. Playwright's local-PNG baseline shape is simpler and runs fully in our existing CI.

## Option C — Defer to per-loop ad-hoc screenshots, no baselines

- **Pros:** zero new infrastructure. Each loop's `loop-{N}-result.md` includes screenshots taken by hand from the running app.
- **Cons:** no CI signal at all. The audit explicitly flagged "Without visual regression, the Workbench → new-look pivot will silently regress trace timelines, studio replay, /admin/observability, learn-player chrome, and the verify-cert flow with no CI signal until a human screenshots them." Punting on the safety net is the failure mode the audit named.
- **Why rejected:** the entire point of Loop 2 is to make subsequent loops *safe*. Deferring means the safety net doesn't land before risk is taken.

## Decision

**Option A.**

The 2–3 MB of committed PNGs is a fair price for a CI-enforced "this is what the app looks like" contract. Tooling-wise it stays inside Playwright — no new CLI, no secrets, no third-party. The cadence matches the loop sequence: when a loop intentionally changes a render, the result doc explicitly notes "Loop X re-blesses baselines for routes Y, Z" and the commit shows the new PNGs alongside the code.

## A few smaller calls within Option A

- **Chromium only.** Webkit baselines double the maintenance without proportional signal — most redesign work targets the canonical render path, and webkit's font subtle differences are noise relative to "did the layout shift". The webkit project stays in place for behavioural e2e specs (smoke / learner-flow / instructor-flow); only visual-regression skips it.
- **`fullPage: true`** captures the entire scroll height. Catalog + dashboard land long on desktop; truncating to viewport would miss below-the-fold cards.
- **`maxDiffPixels: 100`** absorbs anti-aliasing jitter (4–6 pixels per character × ~100 chars on a typical page) without letting actual diffs through. Playwright's default is `0` which is too strict for hosted webfonts that re-flow on cache misses.
- **`threshold: 0.2`** is the per-pixel intensity tolerance — 20% colour delta before a pixel is "different". This matches the docs' recommendation for prose-heavy screenshots.
- **Don't run on workflow_dispatch deploys** — visual regression is a PR / push gate, not a deploy gate. The existing `e2e` job in `ci.yml` already runs on every PR + push; new spec joins automatically.
