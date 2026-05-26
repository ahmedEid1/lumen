/**
 * Loop-6 storageState setup, Loop-8 hardened.
 *
 * Logs in once per seeded role and writes the resulting auth state
 * (cookies + localStorage) to disk; downstream specs reach for the
 * right state via `test.use({ storageState: '.auth/<role>.json' })`
 * instead of calling `login()` themselves.
 *
 * **Loop 8 — switched from UI-form login to direct FastAPI POST.**
 * The previous shape clicked the `<form>` submit button in
 * `/login` to log in. That clicked button has to wait for React
 * hydration before its `onSubmit` binds; under dev-mode JIT
 * compile pressure on a cold-started `/login` route, that wait
 * raced the test's 60s `actionTimeout` non-deterministically.
 * Three VR baselines (dashboard-light, admin-light, studio-light)
 * deferred across Loops 2/4/6 because of this exact race. API-
 * direct login eliminates the race entirely: no form, no
 * hydration, no JIT compile — just a POST to
 * `/api/v1/auth/login` that returns cookies on the response.
 * Playwright's `context.request` shares its cookie jar with
 * `page`, so a subsequent `page.goto(/dashboard)` arrives
 * authenticated.
 *
 * Auth state files land under `apps/frontend/tests/e2e/.auth/*.json`
 * and are gitignored — they contain session cookies + JWTs. CI
 * regenerates them on every run via this setup project.
 */
import { existsSync, mkdirSync } from "node:fs";
import { expect, test as setup } from "@playwright/test";
import { SEED_USERS, type SeedRole } from "./helpers/login";

// Playwright runs at the frontend workspace root (cwd === /work in
// the e2e container). Using a relative path keeps this ESM-safe —
// __dirname isn't defined under `"type": "module"`.
export const AUTH_DIR = "tests/e2e/.auth";

if (!existsSync(AUTH_DIR)) {
  mkdirSync(AUTH_DIR, { recursive: true });
}

export const STORAGE_PATH = {
  student: `${AUTH_DIR}/student.json`,
  teacher: `${AUTH_DIR}/teacher.json`,
  admin: `${AUTH_DIR}/admin.json`,
} as const satisfies Record<SeedRole, string>;

// Default to `localhost:8000` — works on the GHA runner host where
// the ci.yml e2e + accessibility jobs run playwright directly (the
// api container's 8000 is port-mapped to the host). Inside the e2e
// Loop 20 (Codex rescue #6): login goes through the **web origin**
// not the API origin. The Next config rewrites `/api/v1/*` to the
// internal API URL, so a POST to `baseURL/api/v1/auth/login` lands
// on the same FastAPI endpoint but writes the Set-Cookie back on
// the web host. Previously this ran against `E2E_API_BASE_URL`
// directly which, in the docker-compose e2e profile, set cookies
// for host=`api` — the browser then navigated to `web:3000` and
// dropped them. Worked accidentally on host-runs (localhost shared
// across :8000/:3000) but was wrong on cross-host runs.

for (const role of Object.keys(STORAGE_PATH) as SeedRole[]) {
  setup(`authenticate as ${role}`, async ({ page, request }) => {
    const creds = SEED_USERS[role];

    // Login through the web origin so cookies are scoped to
    // baseURL (web:3000 in docker, lumen.ahmedhobeishy.tech in
    // prod-visual mode). `request` here is fixture-scoped and
    // shares cookies with the browser context.
    const res = await request.post("/api/v1/auth/login", {
      data: { email: creds.email, password: creds.password },
      headers: { Accept: "application/json" },
    });
    expect(
      res.ok(),
      `auth/login for ${role} returned ${res.status()} ${res.statusText()}`,
    ).toBeTruthy();

    // Pre-dismiss the onboarding tour via direct localStorage
    // writes before snapshotting. We navigate to the home page
    // (small, fast, always hydrates cleanly) so the page has a
    // document for the script to write into; we don't navigate
    // to /dashboard because that's a longer cold-compile path
    // and adds no value here — we already have the cookies, the
    // dashboard render isn't needed for the storageState capture.
    await page.goto("/");
    await page.evaluate(() => {
      try {
        localStorage.setItem("lumen.onboarding.learner.dismissed", "1");
        localStorage.setItem("lumen.onboarding.instructor.dismissed", "1");
      } catch {
        /* see preDismissOnboarding() in helpers/login.ts */
      }
    });

    await page.context().storageState({ path: STORAGE_PATH[role] });
  });
}
