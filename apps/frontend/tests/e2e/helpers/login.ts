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
 * Options shared by {@link login} and {@link loginAs}.
 *
 * - ``waitForDashboard`` (default true): assert we land on /dashboard.
 * - ``rescueRedirect`` (default false): if the form's client-side
 *   `router.push("/dashboard")` races and parks us at /login, navigate
 *   to /dashboard explicitly (the auth cookie is already set) instead
 *   of failing. This is ONLY for specs whose subject is NOT the login
 *   redirect itself — golden-path flows that just need to reach the
 *   dashboard to test something downstream. The redirect's own
 *   correctness stays asserted strictly by the default (e.g. the
 *   auth.spec.ts password-reset sanity login), so a real regression in
 *   `router.push(next)` is never masked across the whole suite.
 */
export type LoginOpts = {
  waitForDashboard?: boolean;
  rescueRedirect?: boolean;
};

/**
 * Sign in via the /login form and wait until the dashboard URL is
 * reached. Callers that need to land somewhere else can pass
 * ``waitForDashboard: false`` and route afterwards.
 */
export async function login(
  page: Page,
  role: SeedRole,
  opts: LoginOpts = {},
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
  opts: LoginOpts = {},
): Promise<void> {
  const waitForDashboard = opts.waitForDashboard ?? true;
  const rescueRedirect = opts.rescueRedirect ?? false;
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

  if (waitForDashboard && !rescueRedirect) {
    // Default: assert the client-side `router.push("/dashboard")`
    // redirect strictly. This is the canonical coverage for the login
    // redirect (relied on by auth.spec.ts after a password reset), so
    // it must NOT be rescued — a real regression should fail here.
    // QA-iter1: 30s poll because Next.js SPA pushState doesn't emit a
    // fresh document 'load' and webkit under cold-compile parallel
    // pressure exceeds toHaveURL's default 5s ceiling.
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
  } else if (waitForDashboard) {
    // rescueRedirect: for golden-path specs whose subject is NOT the
    // redirect (they just need to reach the dashboard to test
    // something downstream). The `router.push(next)` SPA pushState
    // intermittently races under CI cold-compile parallel pressure and
    // parks at /login (recurring flake across iter-1 + iter-6, both
    // browsers). Assert the URL with a generous poll; if the redirect
    // genuinely didn't fire, navigate explicitly — the session cookie
    // is set by the successful POST above, so /dashboard loads authed.
    // If auth did NOT succeed the goto bounces back to /login and the
    // assertion still fails loudly, so this never green-washes a
    // broken login.
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
