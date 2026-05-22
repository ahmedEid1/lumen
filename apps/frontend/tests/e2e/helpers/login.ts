/**
 * Login helpers used across the H3 golden-path e2e suite.
 *
 * Seeded credentials come from ``apps/backend/app/cli.py`` ``seed`` and
 * are documented in CLAUDE.md:
 *
 *   admin@lumen.test   / Admin!2026
 *   teacher@lumen.test / Teach!2026
 *   student@lumen.test / Learn!2026
 *
 * Helpers prefer the form-scoped Sign-in selector (same pattern the
 * pre-existing smoke / instructor / learner specs use) so the navbar's
 * "Sign in" link doesn't trip Playwright strict mode.
 */
import { expect, type Page } from "@playwright/test";

export const SEED_USERS = {
  admin: { email: "admin@lumen.test", password: "Admin!2026" },
  teacher: { email: "teacher@lumen.test", password: "Teach!2026" },
  student: { email: "student@lumen.test", password: "Learn!2026" },
} as const;

export type SeedRole = keyof typeof SEED_USERS;

/**
 * Sign in via the /login form and wait until the dashboard URL is
 * reached. Callers that need to land somewhere else can pass
 * ``waitForDashboard: false`` and route afterwards.
 */
export async function login(
  page: Page,
  role: SeedRole,
  opts: { waitForDashboard?: boolean } = {},
): Promise<void> {
  const creds = SEED_USERS[role];
  await loginAs(page, creds.email, creds.password, opts);
}

/**
 * Like {@link login} but takes explicit credentials. Used by the
 * auth.spec.ts register-then-login flow where the user is freshly
 * minted and not in the seed set.
 */
export async function loginAs(
  page: Page,
  email: string,
  password: string,
  opts: { waitForDashboard?: boolean } = {},
): Promise<void> {
  const waitForDashboard = opts.waitForDashboard ?? true;
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page
    .locator("form")
    .getByRole("button", { name: /sign in/i })
    .click();
  if (waitForDashboard) {
    await expect(page).toHaveURL(/\/dashboard/);
  }
}

/**
 * Log out via the /api/v1/auth/logout endpoint so the next spec starts
 * from a clean cookie jar. Playwright contexts are normally isolated
 * but tests that share a context (e.g. multiple test() blocks inside
 * one describe with no explicit context separation) benefit from an
 * explicit reset.
 */
export async function logout(page: Page): Promise<void> {
  await page.context().clearCookies();
}
