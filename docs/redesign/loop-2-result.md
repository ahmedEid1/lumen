# Loop 2 — Result

## What shipped

`apps/frontend/tests/e2e/visual-regression.spec.ts` (108 LoC) plus 8 PNG baselines under `visual-regression.spec.ts-snapshots/` totalling 4.3 MB. Captures 4 public routes × 2 themes:

| Route | Dark | Light |
|---|---|---|
| `/` | 1.1 MB | 1.1 MB |
| `/courses` | 1.0 MB | 1.0 MB |
| `/login` | 33 KB | 34 KB |
| `/register` | 39 KB | 40 KB |

Big sizes are home + catalog full-page captures (long pages with hero + pillars + featured grid). Small sizes are auth card layouts on dim surfaces.

| File | Lines changed |
|---|---|
| `apps/frontend/tests/e2e/visual-regression.spec.ts` | +108 / -0 |
| `apps/frontend/tests/e2e/visual-regression.spec.ts-snapshots/*.png` | 8 new files, 4.3 MB |
| `docs/redesign/loop-2-{goal,options,spec,result}.md` | +~400 / -0 |

## Binary criteria — public-only delta

The original spec aimed for 16 baselines (8 routes × 2 themes). 8 shipped. The deferred 8 (auth-gated) are documented in the spec's mid-implementation pivot.

- [x] `tests/e2e/visual-regression.spec.ts` parametrised across the 4 public routes × 2 themes
- [x] Spec uses `test.skip(browserName !== "chromium", …)` to skip webkit
- [x] Spec uses `page.emulateMedia({ colorScheme, reducedMotion: "reduce" })` + `animations: "disabled"`
- [x] Spec sets `localStorage["theme"]` via `addInitScript` before each navigation
- [x] 8 PNGs captured: `home-{dark,light}`, `catalog-{dark,light}`, `login-{dark,light}`, `register-{dark,light}` — all `chromium-linux` suffix
- [x] First `--update-snapshots` run: 8 passed in 16.1s
- [x] Verification re-run (no flag): 8 passed in 12.1s — stable
- [ ] ~~All 16 baselines captured~~ → 8 shipped; 8 deferred to Loop 3
- [ ] ~~Auth-gated routes use `login()` helper~~ → out of scope this loop

## What broke (and what it tells us about Loop 3)

The first `--update-snapshots` run captured all 16 baselines but 6 of the auth-gated 8 landed on the login page instead of the auth target. Root cause: `loginAs()` in `tests/e2e/helpers/login.ts` clicks `<button>Sign in</button>` which is `disabled` until React hydrates. The login form's hydration gate (see AUDIT.md cross-cutting #1 — "Every auth surface re-implements the same `mounted` hydration gate") races the Next.js dev-mode JIT compile on cold `/login`; with 60s `actionTimeout`, the click can hit before hydration releases, the form never submits, and the screenshot lands on `/login` for what was supposed to be `/profile`.

The pre-existing e2e specs (`smoke`, `auth`, `instructor-flow`, `tutor-citations`, `learner-journey`) were independently flaky on the same run — 5 failed, 2 flaky-passed-on-retry. Not introduced by this loop; this loop just amplified the existing fragility by running 16 short tests in close succession against a cold web container.

**This is exactly the problem Loop 3 (`useHydrated()` + `<AuthCard>`) solves.** Once the four duplicated hydration gates collapse into one canonical `useHydrated()` hook that's settled on first mount, the login form's submit button enables predictably and the e2e race goes away. Loop 3 will:
1. Land the `<AuthCard>` + `useHydrated()` primitives.
2. Extend `visual-regression.spec.ts` to add `dashboard`, `profile`, `studio`, `admin` × 2 themes = 8 more baselines.
3. Re-run with confidence that the login click won't beat hydration.

## Verification commands

```
$ docker compose --profile e2e run --rm e2e \
    visual-regression.spec.ts --project=chromium --update-snapshots --reporter=list

Running 8 tests using 2 workers
A snapshot doesn't exist at /work/tests/e2e/visual-regression.spec.ts-snapshots/home-light-chromium-linux.png, writing actual.
…
8 passed (16.1s)

$ docker compose --profile e2e run --rm e2e \
    visual-regression.spec.ts --project=chromium --reporter=list

Running 8 tests using 2 workers
✓  8/8 in 12.1s — stable
```

## 3-bullet retro

- **Reading the ENTRYPOINT saved a 5-minute regression.** First attempt prefixed `pnpm exec playwright test` in the docker compose command, *and* the `Dockerfile.e2e` ENTRYPOINT was already `pnpm exec playwright test` — so the command ended up `pnpm exec playwright test pnpm exec playwright test visual-regression.spec.ts …`. Playwright treated `pnpm`/`exec`/`playwright`/`test` as positional path filters that matched no files, so the filter dropped and the full e2e suite ran (5.7 min, 16 mine + 24 others). Fix: pass *only* the test file + flags as the `docker compose run` args; the ENTRYPOINT prepends `playwright test` automatically.
- **Loop scope follows reality, not the spec doc.** The 16-baseline plan was optimistic; the auth race surfaced something the audit had already named (cross-cutting #1) but I'd planned to fix in Loop 3 anyway. Splitting the loop in flight ("ship the 8 that work, defer the 8 that don't until the primitive that fixes them lands") is the spec doc's "mid-implementation pivot" pattern — document the change in the spec, ship the working delta, note the follow-up.
- **Visual regression is satisfying to ship when it works.** The re-run confirming 8/8 stable in 12.1s is the smallest amount of code (108 LoC + 8 PNGs) for the highest amount of forward safety in this redesign. Loops 3 onwards now have a CI signal for unintended pixel drift on the four public routes that take the most cross-loop edits (`/`, `/courses`, `/login`, `/register` — the front door of the app).

## Follow-ups discovered (not done this loop)

- **Wire the e2e suite to `docker-compose.ci.yml`'s prod-build `web`** for local capture too. Right now `make test.e2e` runs against `pnpm dev` which has the JIT cold-compile fragility. CI already uses the overlay. A new `make test.e2e.ci` (or refactor of `test.e2e` to take a profile flag) would make local runs match CI behaviour. **Schedule:** when a future loop has reason to touch the e2e infrastructure anyway (probably after Loop 3's auth-gated baselines).
- **Add the 8 auth-gated baselines (loops 3+).** Track on Loop 3's task description.
- **Mobile-viewport baselines.** Playwright config has no mobile project today (`chromium` + `webkit` are both Desktop). AUDIT.md §4 #5 flagged the 640–1023px collapse on `/learn/[slug]`; adding a `mobile-chromium` project with `devices["iPhone 14"]` + capturing baselines at that viewport is high-signal for the mobile/tablet pass.
- **README screenshots regenerated alongside.** `screenshots.spec.ts` still generates README PNGs by hand at hardcoded routes; once visual-regression covers the full surface, the README capture can pull from the baseline set instead of re-running its own browser session.

## What to watch in Loop 3

Loop 3 lands `<AuthCard>` + `useHydrated()` + the state / form primitives. Watch:
1. The login form's hydration gate becoming a single canonical `useHydrated()` call site — the e2e auth race should die at that point.
2. The 6 byte-identical auth surfaces (login, register, forgot, reset, verify-email, verify/[id], confirm-email-change — actually 7) collapsing into a `<AuthCard>` composition. Public-route baselines (login + register) will re-bless; that's expected and the result doc must call it out.
3. Adding `dashboard`, `profile`, `studio`, `admin` × 2 themes to `ROUTES` and re-capturing once the login race is gone. 8 new baselines, no regressions on the existing 8.
