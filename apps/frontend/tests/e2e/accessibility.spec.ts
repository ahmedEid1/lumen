/**
 * WCAG 2.2 AA accessibility gate (Phase D5).
 *
 * Runs axe-core inside a real Playwright browser session against the
 * built Next.js app and fails on any AA violation. The April 24 2026
 * WCAG 2.2 AA effective date applies broadly to consumer-facing
 * surfaces, so we lock the audit at `wcag22aa` plus the lower bars it
 * builds on (`wcag2a/aa`, `wcag21a/aa`). Best-practice rules are
 * informational here — they do not gate the build.
 *
 * Routes covered:
 *   public (logged out)
 *     /                    (home)
 *     /courses             (catalog)
 *     /login, /register, /forgot-password
 *     /courses/[first seeded slug]   (course detail)
 *   authenticated
 *     /dashboard           (student)
 *     /profile             (student)
 *     /studio              (instructor)
 *     /admin               (admin)
 *
 * Seeded credentials come from `make seed` (see CLAUDE.md):
 *   student@lumen.test / Learn!2026
 *   teacher@lumen.test / Teach!2026
 *   admin@lumen.test   / Admin!2026
 *
 * Debugging a failure
 * -------------------
 * axe surfaces each violation with the WCAG rule id, the offending
 * CSS selector, an `impact` (minor/moderate/serious/critical) and a
 * `helpUrl` pointing at Deque's docs for the rule. The custom
 * formatter at the bottom of this file prints all four for every
 * failing node so the CI log is enough to triage without re-running.
 *
 * If a rule needs to be temporarily suppressed during triage, prefer
 * `AxeBuilder.disableRules([...])` on the single test that surfaces
 * it (with a `// TODO(a11y):` linking to an issue) over adding the
 * rule to a global ignore list — the goal is to fix violations, not
 * to grow an ignore file.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import type { Result as AxeResult } from "axe-core";

const WCAG_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

/**
 * Pretty-print axe violations so the CI log alone is enough to triage.
 * Each violation lists the rule id, impact, WCAG help URL, and every
 * offending CSS selector + HTML snippet.
 */
function formatViolations(violations: AxeResult[]): string {
  if (violations.length === 0) return "";
  return violations
    .map((v) => {
      const nodes = v.nodes
        .map(
          (n) =>
            `    - target: ${JSON.stringify(n.target)}\n` +
            `      html:   ${n.html.slice(0, 200)}\n` +
            (n.failureSummary
              ? `      why:    ${n.failureSummary.replace(/\n/g, " ")}`
              : ""),
        )
        .join("\n");
      return (
        `\n[${v.impact ?? "n/a"}] ${v.id} — ${v.help}\n` +
        `  rule:    ${v.helpUrl}\n` +
        `  tags:    ${v.tags.filter((t) => t.startsWith("wcag")).join(", ")}\n` +
        `  nodes:\n${nodes}`
      );
    })
    .join("\n");
}

/**
 * Audit a single page after a manual `page.goto`. Caller decides when
 * the page is settled enough to scan (e.g. after a heading appears).
 */
async function expectNoAxeViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG_TAGS)
    .analyze();
  expect(
    results.violations,
    `WCAG AA violations found:${formatViolations(results.violations)}`,
  ).toEqual([]);
}

/**
 * Reusable login helper. The dev login page is pre-filled with the
 * student demo creds, but every authed test fills explicitly so the
 * flow doesn't break if seed defaults change.
 */
async function signIn(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  // Scope to the form to avoid the navbar's "Sign in" link tying with
  // the submit button under Playwright strict mode (same pattern as
  // smoke.spec.ts and instructor-flow.spec.ts).
  await page
    .locator("form")
    .getByRole("button", { name: /sign in/i })
    .click();
  await expect(page).toHaveURL(/\/dashboard/);
}

test.describe("WCAG 2.2 AA — public routes", () => {
  test("home", async ({ page }) => {
    await page.goto("/");
    // Wait for hero so SSR + hydration + theme-aware tokens settle
    // before axe runs (otherwise color-contrast can race the theme).
    // Hero copy is `home.heroTitle1` + `home.heroTitle2`
    // ("Take a path. Become it.") after the Workbench repaint — the
    // previous "Learn anything" selector dates from the pre-pivot hero.
    await expect(
      page.getByRole("heading", { name: /Take a path\.\s+Become it\./i }),
    ).toBeVisible();
    await expectNoAxeViolations(page);
  });

  test("catalog", async ({ page }) => {
    await page.goto("/courses");
    await expect(page.getByRole("heading", { name: /Catalog/i })).toBeVisible();
    await expectNoAxeViolations(page);
  });

  test("login", async ({ page }) => {
    await page.goto("/login");
    await expect(
      page.locator("form").getByRole("button", { name: /sign in/i }),
    ).toBeVisible();
    await expectNoAxeViolations(page);
  });

  test("register", async ({ page }) => {
    await page.goto("/register");
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expectNoAxeViolations(page);
  });

  test("forgot password", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByLabel(/email/i)).toBeVisible();
    await expectNoAxeViolations(page);
  });

  test("course detail (first seeded course)", async ({ page }) => {
    await page.goto("/courses");
    // The Workbench card is a single `<Link>` wrapping a badge row, an
    // <h3> title, an overview, an avatar/owner block, and a meta footer
    // — so the link's accessible name is a noisy concatenation of all
    // of that. Anchor against the h3 (the card's title) instead: a
    // stable accessible-name node that survives seed slug renames the
    // same way the old `a[href^="/courses/"]` selector did, while
    // clicking it still triggers the wrapping anchor's navigation.
    const firstCourseHeading = page
      .getByRole("heading", { level: 3 })
      .first();
    await firstCourseHeading.waitFor();
    await firstCourseHeading.click();
    await expect(page).toHaveURL(/\/courses\/[^/]+$/);
    await expectNoAxeViolations(page);
  });
});

test.describe("WCAG 2.2 AA — authenticated routes", () => {
  test("student dashboard", async ({ page }) => {
    await signIn(page, "student@lumen.test", "Learn!2026");
    await expect(
      page.getByRole("heading", { name: /Welcome/i }),
    ).toBeVisible();
    await expectNoAxeViolations(page);
  });

  test("student profile", async ({ page }) => {
    await signIn(page, "student@lumen.test", "Learn!2026");
    await page.goto("/profile");
    // Profile heading varies by repaint; assert URL settled and one
    // form control is interactive before axe runs.
    await expect(page).toHaveURL(/\/profile/);
    await page.waitForLoadState("networkidle");
    await expectNoAxeViolations(page);
  });

  test("instructor studio", async ({ page }) => {
    await signIn(page, "teacher@lumen.test", "Teach!2026");
    await page.goto("/studio");
    await expect(page).toHaveURL(/\/studio/);
    await page.waitForLoadState("networkidle");
    await expectNoAxeViolations(page);
  });

  test("admin dashboard", async ({ page }) => {
    await signIn(page, "admin@lumen.test", "Admin!2026");
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/admin/);
    await page.waitForLoadState("networkidle");
    await expectNoAxeViolations(page);
  });
});
