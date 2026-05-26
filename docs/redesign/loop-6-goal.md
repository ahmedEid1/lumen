# Loop 6 — Goal

**Unblock the auth-gated visual-regression baselines that Loops 2 and 4 deferred, by wiring Playwright's `storageState` fixtures to bypass per-test login races.**

AUDIT.md §7 originally sequenced Loop 6 as the light-mode redesign. I'm reordering: the storageState infrastructure is smaller (~100 LoC), eliminates two deferred items from earlier loops, and unblocks every future surface loop that needs CI signal on auth-gated routes (dashboard, profile, studio, admin). Light mode shifts to Loop 7 — re-running visual-regression after the light-mode work needs storageState already in place anyway.

- **Surface:**
  - NEW `apps/frontend/tests/e2e/auth.setup.ts` — Playwright "setup" project; logs in as each seeded role (student, teacher, admin), pre-dismisses the onboarding tour, snapshots cookies + localStorage to `tests/e2e/.auth/<role>.json`.
  - MODIFIED `apps/frontend/playwright.config.ts` — adds the setup project; chromium + webkit projects gain `dependencies: ["setup"]`.
  - MODIFIED `apps/frontend/tests/e2e/visual-regression.spec.ts` — split ROUTES into `PUBLIC_ROUTES` (no auth) + `AUTH_ROUTES` (role tagged); auth-gated tests use `test.use({ storageState: ... })`.
  - MODIFIED `.gitignore` — adds `apps/frontend/tests/e2e/.auth/`.
  - NEW baselines: 8 auth-gated × 2 themes = 16 PNGs, *captured* and *committed*.

- **Persona:** every future surface loop. Right now any change to dashboard, profile, studio, or admin ships without VR signal — a "while I'm here" edit that drifts the layout has no CI tripwire. After this loop, the auth-gated routes are baseline-pinned the same way the public routes have been since Loop 2.

- **Binary success criteria:**
  1. `auth.setup.ts` runs 3 tests (one per role); each writes a `.auth/<role>.json` file under the gitignored directory.
  2. `playwright.config.ts` has a "setup" project; `chromium` (+ `webkit`) projects declare `dependencies: ["setup"]`.
  3. `visual-regression.spec.ts` consumes `test.use({ storageState: ... })` per role for the 4 auth-gated route blocks.
  4. First capture pass writes 8 new auth-gated baselines under `visual-regression.spec.ts-snapshots/`.
  5. Verification re-run shows the baselines stable (allowing for CI's `retries: 2` to absorb residual flake).
  6. The fully sweep — `make test.web` — stays green (this loop touches only e2e, not vitest).
  7. STATUS.md row 6 + CHANGELOG `### Added (UI redesign loop 6)`.

Out of scope:
- Light-mode design (now Loop 7).
- Fixing pre-existing e2e specs (smoke, learner-flow) that have their own flakiness — the storageState pattern is *available* to them but migrating is a separate sweep.
- Pre-built `pnpm start` for the e2e profile (would eliminate the JIT cold-compile entirely; tracked as a follow-up).
