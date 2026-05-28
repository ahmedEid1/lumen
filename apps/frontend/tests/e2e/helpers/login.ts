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
  // QA-iter1: wait for React's controlled-input onChange to be
  // bound. Without this, on webkit specifically `fill()` lands
  // pre-hydration and the controlled inputs never see the typed
  // text — onSubmit then ships `{email: "", password: ""}`.
  await page.locator('form[data-hydrated="true"]').waitFor();
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  // Couple the click with the login POST so we know the submit
  // handler was bound AND the request actually fired before we assert
  // on navigation. `data-hydrated` already gates the input/submit
  // binding race; this additionally pins the "did auth succeed"
  // signal so the dashboard assertion below is decoupled from the
  // client-side `router.push` timing.
  const loginPost = page
    .waitForResponse(
      (r) =>
        r.url().includes("/api/v1/auth/login") &&
        r.request().method() === "POST",
      { timeout: 30_000 },
    )
    .catch(() => null);
  await page
    .locator("form")
    .getByRole("button", { name: /sign in/i })
    .click();
  const resp = await loginPost;

  if (waitForDashboard) {
    // QA-iter7: the `router.push(next)` that the login form fires on
    // success is a Next.js SPA pushState — it does NOT emit a fresh
    // document 'load', and under CI cold-compile parallel pressure it
    // intermittently races and leaves the page parked at /login
    // (recurring flake across iter-1 + iter-6; iter-1 shipped the
    // data-hydrated + one-shot-forward mitigations, which reduced but
    // didn't eliminate it on chromium AND webkit). Auth itself is
    // fine — manual prod logins always redirect.
    //
    // So: assert the dashboard URL with a generous poll; if the SPA
    // redirect genuinely didn't fire, navigate explicitly. The session
    // cookie is set by the successful POST above, so /dashboard loads
    // authenticated. This ONLY rescues a raced client redirect — if
    // auth actually failed (no cookie), the explicit goto bounces back
    // to /login and the final assertion still fails loudly.
    try {
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
    } catch {
      if (resp && resp.ok()) {
        await page.goto("/dashboard");
        await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
      } else {
        throw new Error(
          `login(${email}) did not reach /dashboard and the auth POST ` +
            `did not succeed (status ${resp?.status() ?? "no response"})`,
        );
      }
    }
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
