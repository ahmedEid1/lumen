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
 * First-login onboarding tour (`apps/frontend/src/components/onboarding/
 * onboarding-tour.tsx`) renders as a `role="dialog" aria-modal="true"`
 * full-viewport overlay on `/dashboard` (learner) and `/studio`
 * (instructor + admin) the first time a user visits. The dismissal is
 * persisted in localStorage. Playwright contexts start with empty
 * localStorage, so the tour ALWAYS shows in CI and intercepts pointer
 * events on every studio button — that's why
 * `ingest-multimodal.spec.ts` and `instructor-golden.spec.ts` time out
 * trying to click `Import from URL` / `New course` for the full 60s
 * actionTimeout window. Preseed both keys via `addInitScript` (runs
 * before any page script on every navigation) so the tour treats both
 * roles as already-dismissed and never mounts the overlay. Keys come
 * from `apps/frontend/src/app/{dashboard,studio}/page.tsx` —
 * `lumen.onboarding.learner.dismissed` and
 * `lumen.onboarding.instructor.dismissed`.
 */
export async function preDismissOnboarding(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("lumen.onboarding.learner.dismissed", "1");
      localStorage.setItem("lumen.onboarding.instructor.dismissed", "1");
    } catch {
      /* Storage access can be blocked in odd browser modes; the worst
         case is the tour shows and a downstream test fails — which is
         exactly the status quo without this helper. */
    }
  });
}

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
  await preDismissOnboarding(page);
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
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
