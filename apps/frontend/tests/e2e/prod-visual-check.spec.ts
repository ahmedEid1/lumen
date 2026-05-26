/**
 * Post-deploy prod visual + walkthrough. Run against the LIVE
 * production URL, NOT the local dev stack. Two passes:
 *
 *   1. STATIC CAPTURES — 4 public routes × 2 themes = 8 fullPage PNGs.
 *      Quick sanity sheet for "did the deploy land cleanly".
 *
 *   2. WALKTHROUGH — Playwright actively navigates a public-only
 *      flow (home → catalog → first course detail → login (view-only) →
 *      register (view-only)), capturing a screenshot AT EACH STEP and
 *      asserting basic page-loaded content. The screenshots are
 *      numbered so the sequence reads as a click-through.
 *
 * Both passes write PNGs under `test-results/prod-visual/` (relative
 * to `cwd === /work` inside the e2e container, which maps to
 * `apps/frontend/test-results/prod-visual/` on the host).
 *
 * Auth-gated routes are deliberately out of scope: prod has real
 * user data, and we don't poke it from a script.
 *
 * Usage:
 *   E2E_BASE_URL=https://lumen.ahmedhobeishy.tech \
 *   docker compose --profile e2e run --rm \
 *     e2e prod-visual-check.spec.ts --project=chromium --reporter=list
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

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
