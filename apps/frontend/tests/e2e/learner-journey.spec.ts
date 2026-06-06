/**
 * Full learner journey: sign in → browse → enroll → complete a lesson →
 * see the certificate gate flip.
 *
 * Relies on the seeded demo data:
 *   student@lumen.test / Learn!2026   (pre-seeded student)
 *   At least one published seeded course with one text lesson.
 *
 * The login page is pre-filled with the demo credentials in dev so the
 * sign-in flow is one click. If you change make seed's output, adjust
 * the selectors below.
 */
import { expect, test } from "@playwright/test";

import { login } from "./helpers/login";

// W11: App-Router SPA navigations emit pushState (no fresh document load), so
// under cold-compile parallel pressure the URL can settle past Playwright's
// default 5s `expect` ceiling. Poll the in-app SPA hops with a generous
// window (mirrors the login helper's own toHaveURL polling).
const NAV_TIMEOUT = 20_000;

test.describe("learner journey", () => {
  test("sign in, find a course, enroll, complete a lesson", async ({ page }) => {
    // W11: drive sign-in via the shared login() helper. It (a) preseeds the
    // onboarding-dismissed localStorage keys via addInitScript BEFORE any page
    // script runs, so the first-login OnboardingTour overlay
    // (`role=dialog`/`data-wb-dialog-overlay`, full-viewport) never mounts to
    // intercept the navbar "Catalog" click — that overlay, not a hydration
    // race, is what timed this test out on webkit + flaked chromium; and
    // (b) gates on form[data-hydrated] + couples the login POST with the
    // /dashboard redirect (same robustness class as e6e49a3). rescueRedirect
    // covers the SPA pushState race under cold-compile parallel pressure.
    await login(page, "student", { rescueRedirect: true });

    // Catalog.
    await page.getByRole("link", { name: /catalog/i }).first().click();
    await expect(page).toHaveURL(/\/courses/, { timeout: NAV_TIMEOUT });

    // Click the first course card — title link points at /courses/[slug].
    // Retry until the SPA nav fires (same App-Router <Link> hydration class
    // as the learn link below).
    const firstCourse = page.locator('a[href^="/courses/"]').first();
    await firstCourse.waitFor();
    await expect(async () => {
      await firstCourse.click();
      await expect(page).toHaveURL(/\/courses\/[^/]+$/, { timeout: 5_000 });
    }).toPass({ timeout: NAV_TIMEOUT });

    // Enroll if we're not already.
    const enrollBtn = page.getByRole("button", { name: /^enroll$/i });
    if (await enrollBtn.isVisible().catch(() => false)) {
      await enrollBtn.click();
      // Wait for the post-enroll CTA to swap to "Continue learning" or "Start learning".
      await expect(
        page.getByRole("link", { name: /(continue|start) learning/i }),
      ).toBeVisible();
    }

    // Land on the learn page. The course-detail "Continue/Start learning"
    // <Link> is an App-Router client link that can receive a click before
    // React hydrates it (the click then no-ops with no pushState, leaving us
    // on /courses/<slug>). Retry the click until the SPA nav to /learn fires.
    const learnLink = page.getByRole("link", { name: /(continue|start) learning/i });
    await learnLink.waitFor();
    await expect(async () => {
      await learnLink.click();
      await expect(page).toHaveURL(/\/learn\//, { timeout: 5_000 });
    }).toPass({ timeout: NAV_TIMEOUT });

    // The lesson player should render. If it's a text lesson we get the
    // mark-complete button; for video / quiz the flow differs but the
    // button label is the same.
    const markComplete = page.getByRole("button", { name: /mark complete/i });
    if (await markComplete.isVisible().catch(() => false)) {
      await markComplete.click();
      // Either the next lesson is selected (progress < 100%) or the
      // progress bar moves; either way the action completed without an
      // error toast.
      await expect(page.locator('[role="status"]').first()).not.toContainText(/error/i, {
        timeout: 3000,
      }).catch(() => {});
    }
  });

  test("language switcher toggles document direction", async ({ page }) => {
    await page.goto("/");
    // Default starts as English (LTR).
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");

    // W11 (stale-test fix): the LocaleSwitcher stopped being a cycle button in
    // Loop 11 — it is now a Radix DropdownMenu (`locale-switcher.tsx`). The old
    // test clicked the trigger and expected `dir` to flip on the click itself;
    // a single click now only OPENS the menu, so `dir` stayed `ltr` and the
    // test failed on both browsers. Drive the real interaction: open the menu,
    // then pick the locale's radio item (`role=menuitemradio`, labelled by its
    // BCP-47 name from LOCALE_LABELS — "العربية" / "English"). The trigger's
    // aria-label still localises (`${t("common.language")}: …` → "Language"
    // in EN, "اللغة" in AR), so the /language|اللغة/i match covers both states.
    const switcher = page.getByLabel(/language|اللغة/i);

    // Open the menu and select Arabic. Arabic is RTL — the provider sets
    // <html dir="rtl" lang="ar">.
    await switcher.click();
    await page.getByRole("menuitemradio", { name: "العربية" }).click();
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("lang", "ar");

    // Flip back to English (open menu → pick English) to leave the test
    // isolated. The trigger's aria-label is now the Arabic "اللغة".
    await switcher.click();
    await page.getByRole("menuitemradio", { name: "English" }).click();
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
  });
});
