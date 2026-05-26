# Loop 8 — Goal

**Replace the UI-form login in `auth.setup.ts` with direct FastAPI POST calls, eliminating the dev-mode JIT-compile race that's been deferring three auth-gated light-mode visual-regression baselines since Loop 6.**

Audit + Loop 6 + Loop 7 deferral trail: the Playwright setup project's `loginAs()` helper clicks the `/login` form's submit button. That click has to wait for React hydration to bind `onSubmit`; under dev-mode JIT compile pressure on a cold-started `/login`, the wait races the 60s actionTimeout non-deterministically. `dashboard-light`, `admin-light`, `studio-light` baselines have been deferred across three loops because of this exact race.

The fix is small (~60 LoC): POST directly to `/api/v1/auth/login` from inside the setup project. Playwright's `context.request` shares its cookie jar with the test's `page`, so subsequent `page.goto(/dashboard)` calls arrive authenticated. No form, no hydration, no JIT compile.

- **Surface:**
  - `apps/frontend/tests/e2e/auth.setup.ts` — rewrite to use `context.request.post()` against `/api/v1/auth/login` instead of UI form.
  - `docker-compose.yml` — set `E2E_API_BASE_URL: http://api:8000` on the e2e service so the setup can reach the api container via docker network.
  - `apps/frontend/tests/e2e/visual-regression.spec.ts` — un-skip the 3 deferred light baselines now that auth is reliable.
  - Re-bless / capture: 3 new baselines (dashboard-light, admin-light, studio-light) + likely the 3 corresponding dark ones if the new auth flow shifts anything.

- **Persona:** every future surface loop touching dashboard / studio / admin / profile — those routes had no VR signal under light theme. After Loop 8, all 16 auth-gated × theme combos are baseline-pinned.

- **Binary success criteria:**
  1. `auth.setup.ts` uses `context.request.post()` for all 3 roles, not the UI form.
  2. `docker-compose.yml` e2e service sets `E2E_API_BASE_URL`.
  3. `visual-regression.spec.ts` no longer has the `test.skip(true)` block for dashboard/admin/studio under light theme.
  4. 16 baselines committed: 8 public + 8 auth-gated. All capture stably on the initial `--update-snapshots` pass.
  5. Residual flake on verification re-runs is acceptable iff CI's `retries: 2` consistently absorbs it (≤2 retries needed across the suite).
  6. STATUS.md row 8 + CHANGELOG `### Added (UI redesign loop 8)`.

Out of scope:
- Migrating other e2e specs (smoke, auth, learner-flow, instructor-flow) to API-based login. They each have their own loginAs() races. Defer until they themselves are the bottleneck.
- Moving e2e to docker-compose.ci.yml's prod-build web service. Bigger infrastructure change; defer until needed.
- Investigating the residual ~1000-pixel render jitter on re-runs. That's a sub-1% diff that CI's retries can absorb; deeper investigation can wait until it's actually breaking something.
