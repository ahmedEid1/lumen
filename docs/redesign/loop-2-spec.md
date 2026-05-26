# Loop 2 — Spec

## Mid-implementation pivot (2026-05-26)

**The original 16-baseline scope shipped only the 8 public-route baselines.** When I ran the initial `--update-snapshots` pass, the auth-gated routes (`/dashboard`, `/profile`, `/studio`, `/admin`) raced the login form's hydration gate in the dev-mode docker e2e environment — the `disabled:opacity-50` submit button stayed `disabled` for longer than the 60s `actionTimeout` on a cold-compiled `/login`. The first attempts captured the *login page* for those routes instead of the post-login target (file size = 33–34 KB instead of the expected 100–300+ KB).

Two mitigations were considered:
1. Wire the e2e suite to the `docker-compose.ci.yml` overlay's prod-build `web` (no cold compile).
2. Wait for Loop 3 to land `useHydrated()` + `<AuthCard>`, which collapse the four hand-rolled hydration gates into one predictable shape that's faster to settle.

Decision: defer auth-gated baselines. The 8 public-route baselines are coherent and trustworthy on their own; bundling broken auth screenshots into this loop's commit would poison the baseline set. The next loop that touches the auth surfaces (Loop 3 — Foundation C) is the natural place to add the auth-gated baselines, because that loop is *already* going to update them.

The spec below describes the 8-baseline shape that actually shipped.

## Visual sketch

This loop is *itself* the visual sketch. The output is 8 PNG files plus one spec file. The shape per baseline is:

```
+---------------------------------------------------+
|  <Workbench chrome — header, body, footer>        |
|  fullPage capture, scroll height included         |
|  rendered at 1280×720 viewport (chromium default) |
|  theme = dark | light (per parametrised test)    |
+---------------------------------------------------+
```

## File layout

```
apps/frontend/tests/e2e/
├── visual-regression.spec.ts                         (NEW — ~120 LoC)
└── visual-regression.spec.ts-snapshots/              (NEW — Playwright creates)
    ├── home-dark-chromium-linux.png                  (1.1 MB — long home page, both themes)
    ├── home-light-chromium-linux.png                 (1.1 MB)
    ├── catalog-dark-chromium-linux.png               (1.0 MB — long course grid)
    ├── catalog-light-chromium-linux.png              (1.0 MB)
    ├── login-dark-chromium-linux.png                 (33 KB — single-card layout)
    ├── login-light-chromium-linux.png                (34 KB)
    ├── register-dark-chromium-linux.png              (39 KB)
    └── register-light-chromium-linux.png             (40 KB)
```

Auth-gated baselines (`dashboard`, `profile`, `studio`, `admin`) are NOT in this loop. See the mid-implementation pivot above.

## State model

Stateless tests. Each `test()` block:

1. Skips on non-chromium browsers.
2. Pre-injects `localStorage["theme"]` via `addInitScript` (next-themes reads this key on mount; setting it before navigation avoids a flash-of-wrong-theme).
3. Pre-dismisses onboarding tours via the existing `preDismissOnboarding()` helper.
4. For auth-gated routes, calls `login()` with the appropriate `SeedRole`.
5. Navigates to the route.
6. Waits for `networkidle`.
7. `expect(page).toHaveScreenshot()`.

## Data contract

Depends on `make seed` having run — three accounts present:
- `student@lumen.test` / `Learn!2026`
- `teacher@lumen.test` / `Teach!2026`
- `admin@lumen.test` / `Admin!2026`

The seeded data also drives the `/dashboard`, `/studio`, `/admin` page contents (enrolment counts, course list, user table). If the seed changes shape (a new column, a renamed badge), the affected baselines re-bless in that change's commit. AUDIT.md §6 already calls out that "seed/fixture changes are out-of-scope for this redesign" — so the seed is stable for the duration.

## Accessibility

This loop doesn't change rendered output; a11y status is unchanged. The skip-link still works, focus rings still render, axe is still happy. The screenshots will *capture* a11y artefacts (`aria-current` highlight on nav, focus ring on body load), so a future a11y regression that removes one of these will show up as a pixel diff and gate the loop.

## Edge cases

- **Animation timing.** `globals.css:139-145` already forces `animation-duration: 0.001ms` under `prefers-reduced-motion: reduce`. Playwright honours that media query by default in chromium projects. Belt-and-braces: pass `colorScheme: theme === "light" ? "light" : "dark"` AND `reducedMotion: "reduce"` to `page.emulateMedia()` before screenshot.
- **Webfont swap-in.** Inter loads from `next/font/google` which Next bakes into the CSS. There's no FOIT/FOUT in dev mode that would shift baselines.
- **`/admin`'s stats cards** render numbers that depend on seeded counts. Stable across re-seeds because the seed is deterministic; flaky only if a previous test in the suite mutated state (it shouldn't — no test creates a course as part of its happy path). If we ever see a flake here, the route gets a stat-card mask via `expect(page).toHaveScreenshot({ mask: [...] })`.
- **`/profile` includes the user's full name** — `Student User` from the seed. Stable as long as the seed values stay (CLAUDE.md table is the contract).
- **`/courses` cover images** load lazily. `waitForLoadState("networkidle")` should catch them; if a flake surfaces, add an explicit `await page.waitForSelector('img[src*="cover_url"]', { state: "visible" })`.
- **`/studio` shows the instructor's course list** — same stability as `/admin`.

## Implementation order

1. Write `tests/e2e/visual-regression.spec.ts` per Option A.
2. Bring up `docker compose up -d` (already up) + run `make seed` (idempotent; refresh seed data if it's drifted).
3. Run `pnpm exec playwright test visual-regression.spec.ts --update-snapshots --project=chromium` against the live stack. Captures 16 baselines.
4. Run again *without* `--update-snapshots` — all 16 should pass.
5. Verify the captured baselines look right by visual inspection of a few PNGs (`xdg-open`/`feh`).
6. Verify the existing 10 e2e specs still pass (no cross-test interference).
7. Run `make test.web` for the unit-suite sanity check (no spillover to vitest).
8. Commit: spec + 16 baselines + STATUS.md row + CHANGELOG entry. Bigger than typical commit because of the PNGs, but they're the loop's deliverable.

## Binary success criteria (review checklist)

- [ ] `tests/e2e/visual-regression.spec.ts` exists, parametrised across 8 routes × 2 themes.
- [ ] Spec uses `test.skip(browserName !== "chromium", …)` to skip webkit.
- [ ] `tests/e2e/visual-regression.spec.ts-snapshots/` contains exactly 16 `.png` files named `<route>-<theme>-chromium-linux.png`.
- [ ] Spec uses the existing `login()` + `preDismissOnboarding()` helpers (no inline auth duplication).
- [ ] Spec sets `localStorage["theme"]` via `addInitScript` before each navigation.
- [ ] Spec calls `page.emulateMedia({ reducedMotion: "reduce" })` before screenshot.
- [ ] `pnpm exec playwright test visual-regression.spec.ts --project=chromium` returns 16/16 passing against the freshly captured baselines.
- [ ] All other e2e specs still pass — `pnpm exec playwright test --project=chromium` total time ≤ 6 min.
- [ ] `make test.web` still green.
- [ ] STATUS.md row appended.
- [ ] CHANGELOG entry under `### Added (UI redesign loop 2)` describes the baseline contract.
