/**
 * Loop-6 storageState setup. Runs as the "setup" Playwright project
 * before any chromium/webkit project starts. Logs in once per seeded
 * role and writes the resulting auth state (cookies + localStorage)
 * to disk; downstream specs reach for the right state via
 * `test.use({ storageState: '.auth/<role>.json' })` instead of
 * calling `login()` themselves.
 *
 * Why this exists — the `loop-2-result.md` + `loop-4-result.md`
 * deferrals both name the same root cause: per-test `login()` races
 * either the form hydration gate OR the auth-context propagation
 * before `page.goto(target_route)`. Pre-baked storage state eliminates
 * both races: tests start with the user already authenticated, no
 * login click needed.
 *
 * Auth state files land under `apps/frontend/tests/e2e/.auth/*.json`
 * and are gitignored — they contain session cookies + JWTs. CI
 * regenerates them on every run via this setup project. The
 * setup runs sequentially (default workers=1 for "setup" project) so
 * three roles take ~3 × cold-login time, which is faster than per-
 * test login × 8 in the previous shape.
 */
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test as setup } from "@playwright/test";
import { SEED_USERS, preDismissOnboarding, type SeedRole } from "./helpers/login";

// Playwright runs at the frontend workspace root (cwd === /work in
// the e2e container). Using a relative path keeps this ESM-safe —
// __dirname isn't defined under `"type": "module"`.
export const AUTH_DIR = "tests/e2e/.auth";

if (!existsSync(AUTH_DIR)) {
  mkdirSync(AUTH_DIR, { recursive: true });
}

export const STORAGE_PATH = {
  student: join(AUTH_DIR, "student.json"),
  teacher: join(AUTH_DIR, "teacher.json"),
  admin: join(AUTH_DIR, "admin.json"),
} as const satisfies Record<SeedRole, string>;

for (const role of Object.keys(STORAGE_PATH) as SeedRole[]) {
  setup(`authenticate as ${role}`, async ({ page }) => {
    const creds = SEED_USERS[role];
    // Pre-dismiss the onboarding tour overlay before the first nav
    // so the resulting localStorage carries the dismissals — every
    // future test that loads from this state starts past the tour.
    await preDismissOnboarding(page);

    await page.goto("/login");
    await page.getByLabel(/email/i).fill(creds.email);
    await page.getByLabel(/password/i).fill(creds.password);
    await page
      .locator("form")
      .getByRole("button", { name: /sign in/i })
      .click();
    // Wait until the URL settles on /dashboard so the auth context
    // is fully written (cookies + localStorage). storageState()
    // snapshots whatever the browser currently has, so timing here
    // is load-bearing.
    await expect(page).toHaveURL(/\/dashboard/);
    // Add a small settle window so any post-login effects flush
    // (auth/store hydration etc.) before we snapshot.
    await page.waitForTimeout(500);

    await page.context().storageState({ path: STORAGE_PATH[role] });
  });
}
