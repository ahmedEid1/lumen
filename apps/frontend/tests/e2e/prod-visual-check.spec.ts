/**
 * Post-deploy prod visual + walkthrough. Run against the LIVE
 * production URL, NOT the local dev stack. Three passes:
 *
 *   1. STATIC PUBLIC — 4 public routes × 2 themes = 8 fullPage PNGs.
 *      Quick sanity sheet for "did the deploy land cleanly".
 *
 *   2. PUBLIC WALKTHROUGH — home → catalog → first course detail →
 *      login (view-only) → register (view-only).
 *
 *   3. AUTH-GATED CAPTURES — sign in as student/instructor/admin via
 *      the API (no UI form submit, no mutations) then navigate each
 *      role's primary surfaces. User feedback 2026-05-26: "everything
 *      is to be tested" — public-only captures don't gate /studio,
 *      /admin/*, /dashboard/* changes.
 *
 * All passes write PNGs under `test-results/prod-visual/` (relative
 * to `cwd === /work` inside the e2e container, which maps to
 * `apps/frontend/test-results/prod-visual/` on the host).
 *
 * Auth-gated pass is READ-ONLY: navigate + screenshot. No mutations,
 * no destructive button clicks. Uses the seeded test accounts that
 * also exist in prod:
 *   student@lumen.test / Learn!2026
 *   teacher@lumen.test / Teach!2026
 *   admin@lumen.test   / Admin!2026
 *
 * Usage:
 *   E2E_BASE_URL=https://lumen.ahmedhobeishy.tech \
 *   docker compose --profile e2e run --rm \
 *     e2e prod-visual-check.spec.ts --project=chromium --reporter=list
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const OUT_DIR = process.env.PROD_VISUAL_OUT ?? "test-results/prod-visual";
mkdirSync(OUT_DIR, { recursive: true });

const ROUTES = [
  { name: "home", path: "/" },
  { name: "catalog", path: "/courses" },
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
] as const;

const THEMES = ["dark", "light"] as const;

async function pinTheme(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
      const html = document.documentElement;
      if (t === "light") {
        html.classList.add("light");
        html.classList.remove("dark");
        html.style.colorScheme = "light";
      } else {
        html.classList.add("dark");
        html.classList.remove("light");
        html.style.colorScheme = "dark";
      }
    } catch {
      /* ignore */
    }
  }, theme);
}

test.describe("prod visual review — static captures", () => {
  for (const route of ROUTES) {
    for (const theme of THEMES) {
      test(`${route.name} (${theme})`, async ({ page, browserName }) => {
        test.skip(
          browserName !== "chromium",
          "prod visual review is pinned to chromium",
        );

        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
        await pinTheme(page, theme);

        await page.goto(route.path, { waitUntil: "networkidle" });
        await page.waitForTimeout(500);

        await page.screenshot({
          path: join(OUT_DIR, `${route.name}-${theme}.png`),
          fullPage: true,
          animations: "disabled",
        });
      });
    }
  }
});

test.describe("prod visual review — walkthrough (dark theme, public only)", () => {
  test("home → catalog → first course → login (view) → register (view)", async ({
    page,
    browserName,
  }) => {
    test.skip(browserName !== "chromium", "walkthrough pinned to chromium");

    await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
    await pinTheme(page, "dark");

    // Step 1 — home loads
    await page.goto("/", { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page.screenshot({
      path: join(OUT_DIR, "walkthrough-01-home.png"),
      fullPage: false, // viewport capture for above-the-fold focus
    });
    await expect(page.locator("h1").first()).toBeVisible();

    // Step 2 — click "Catalog" in the nav → /courses
    await page.getByRole("link", { name: /catalog/i }).first().click();
    await page.waitForURL(/\/courses/);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await page.screenshot({
      path: join(OUT_DIR, "walkthrough-02-catalog.png"),
      fullPage: false,
    });
    await expect(page.getByRole("heading", { name: /catalogue|catalog/i })).toBeVisible();

    // Step 3 — click the first course card → /courses/[slug]
    const firstCourseCard = page.locator("a[href^='/courses/']").first();
    const courseHref = await firstCourseCard.getAttribute("href");
    expect(courseHref).toBeTruthy();
    await firstCourseCard.click();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await page.screenshot({
      path: join(OUT_DIR, "walkthrough-03-course-detail.png"),
      fullPage: true, // full-page here so we capture the syllabus + reviews
    });
    // Course-detail page should have a h1 with the course title.
    await expect(page.locator("h1").first()).toBeVisible();

    // Step 4 — back to home, then to login
    await page.goto("/", { waitUntil: "networkidle" });
    await page.getByRole("link", { name: /sign in/i }).first().click();
    await page.waitForURL(/\/login/);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await page.screenshot({
      path: join(OUT_DIR, "walkthrough-04-login.png"),
      fullPage: false,
    });
    // Don't actually submit — public flow only. Just verify the form is hydrated.
    await expect(page.getByLabel(/email/i)).toBeVisible();

    // Step 5 — register link from login
    await page.getByRole("link", { name: /create an account|register|sign up/i })
      .first()
      .click();
    await page.waitForURL(/\/register/);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await page.screenshot({
      path: join(OUT_DIR, "walkthrough-05-register.png"),
      fullPage: false,
    });
    await expect(page.getByLabel(/email/i)).toBeVisible();
  });
});

// ────────────────────────────────────────────────────────────────────
// AUTH-GATED PASS
// ────────────────────────────────────────────────────────────────────
//
// API-login (no UI form submit) into a fresh BrowserContext per role,
// then navigate read-only to each surface and capture. Same accounts
// that exist in seed data and ALSO exist in prod (verified 2026-05-26
// via `curl /api/v1/auth/login` — the seeded test accounts are in
// prod too).
//
// No mutations: don't click destructive buttons, don't toggle role/
// active, don't create courses. We're checking that the page rendered
// correctly, not load-testing the API.

const CREDS = {
  student: { email: "student@lumen.test", password: "Learn!2026" },
  instructor: { email: "teacher@lumen.test", password: "Teach!2026" },
  admin: { email: "admin@lumen.test", password: "Admin!2026" },
} as const;

async function apiLogin(
  context: BrowserContext,
  baseUrl: string,
  email: string,
  password: string,
): Promise<void> {
  const res = await context.request.post(`${baseUrl}/api/v1/auth/login`, {
    data: { email, password },
    headers: { Accept: "application/json" },
  });
  if (!res.ok()) {
    throw new Error(
      `API login failed for ${email}: ${res.status()} ${await res.text()}`,
    );
  }
  // Cookies are set by the server (HttpOnly auth cookie). The
  // BrowserContext now carries them; navigating to any auth-gated
  // path will load as that user.
}

/**
 * Pin theme + sign in + capture a list of routes. Used by all three
 * role passes below.
 */
async function captureAuthedRoutes(
  context: BrowserContext,
  baseUrl: string,
  creds: { email: string; password: string },
  rolePrefix: string,
  routes: { name: string; path: string; fullPage?: boolean }[],
): Promise<void> {
  await apiLogin(context, baseUrl, creds.email, creds.password);
  const page = await context.newPage();
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await pinTheme(page, "dark");
  for (const r of routes) {
    await page.goto(r.path, { waitUntil: "networkidle" });
    await page.waitForTimeout(800); // settle async data
    await page.screenshot({
      path: join(OUT_DIR, `auth-${rolePrefix}-${r.name}.png`),
      fullPage: r.fullPage ?? true,
      animations: "disabled",
    });
  }
  await page.close();
}

test.describe("prod visual review — auth-gated as student", () => {
  test("dashboard + reviews + mastery + path + profile", async ({
    browser,
    browserName,
    baseURL,
  }) => {
    test.skip(browserName !== "chromium", "auth-gated pass pinned to chromium");
    const base = baseURL ?? "https://lumen.ahmedhobeishy.tech";
    const context = await browser.newContext();
    try {
      await captureAuthedRoutes(context, base, CREDS.student, "student", [
        { name: "dashboard", path: "/dashboard" },
        { name: "reviews", path: "/dashboard/reviews" },
        { name: "mastery", path: "/dashboard/mastery" },
        { name: "path", path: "/dashboard/path" },
        { name: "profile", path: "/profile" },
      ]);
    } finally {
      await context.close();
    }
  });
});

test.describe("prod visual review — auth-gated as instructor", () => {
  test("studio list + studio detail (first own course)", async ({
    browser,
    browserName,
    baseURL,
  }) => {
    test.skip(browserName !== "chromium", "auth-gated pass pinned to chromium");
    const base = baseURL ?? "https://lumen.ahmedhobeishy.tech";
    const context = await browser.newContext();
    try {
      await apiLogin(context, base, CREDS.instructor.email, CREDS.instructor.password);
      const page = await context.newPage();
      await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
      await pinTheme(page, "dark");

      // /studio list
      await page.goto("/studio", { waitUntil: "networkidle" });
      await page.waitForTimeout(800);
      await page.screenshot({
        path: join(OUT_DIR, "auth-instructor-studio.png"),
        fullPage: true,
        animations: "disabled",
      });

      // /studio/[id] for the first own course (deep nesting — exercises Breadcrumb)
      const firstStudioCard = page.locator("a[href^='/studio/']").first();
      const href = await firstStudioCard.getAttribute("href");
      if (href && href !== "/studio/new" && href.length > 8) {
        await firstStudioCard.click();
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: join(OUT_DIR, "auth-instructor-studio-detail.png"),
          fullPage: true,
          animations: "disabled",
        });
      }
      await page.close();
    } finally {
      await context.close();
    }
  });
});

test.describe("prod visual review — auth-gated as admin", () => {
  test("admin counters + users + courses + audit + observability", async ({
    browser,
    browserName,
    baseURL,
  }) => {
    test.skip(browserName !== "chromium", "auth-gated pass pinned to chromium");
    const base = baseURL ?? "https://lumen.ahmedhobeishy.tech";
    const context = await browser.newContext();
    try {
      await captureAuthedRoutes(context, base, CREDS.admin, "admin", [
        { name: "home", path: "/admin" },
        { name: "users", path: "/admin/users" },
        { name: "courses", path: "/admin/courses" },
        { name: "audit", path: "/admin/audit" },
        { name: "observability", path: "/admin/observability" },
      ]);
    } finally {
      await context.close();
    }
  });
});
