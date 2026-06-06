import { test, expect } from "@playwright/test";
import { login } from "./helpers/login";

test.describe("smoke", () => {
  test("home page loads with hero", async ({ page }) => {
    await page.goto("/");
    // W11: the live hero heading is the agent-replay hero (see
    // src/components/home/agent-replay-hero.tsx). Its <h1 id="hero-headline">
    // composes home.heroTitle1 ("Take a path.") + home.heroTitle2
    // ("Become it.") — so its accessible name is "Take a path. Become it.".
    // The old /Learn anything/i expectation predated the replay-hero rebuild
    // and never matched the shipped copy.
    await expect(
      page.getByRole("heading", { name: /Take a path/i }),
    ).toBeVisible();
    // The hero CTA deep-links to the live tutor demo. ("Browse courses" was
    // stale copy; the catalogue link is asserted in the navigation test.)
    await expect(
      page.getByRole("link", { name: /Try the demo/i }),
    ).toBeVisible();
  });

  test("can navigate to catalog", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Catalog/i }).first().click();
    await expect(page).toHaveURL(/\/courses/);
    // The catalogue page <h1> reads "Every subject, catalogued"
    // (catalog hero copy). Match on /catalogue/i which covers the heading
    // without binding to the exact two-line composition.
    await expect(
      page.getByRole("heading", { name: /catalogued/i }),
    ).toBeVisible();
  });

  test("student signs in and reaches dashboard", async ({ page }) => {
    // W11: the old version clicked the form's Sign-in button on a plain
    // /login with NO credentials filled. /login only prefills the demo
    // creds when `?demo=1` is set (src/app/login/page.tsx), so the submit
    // posted an empty body, 422'd, and the page never left /login — the
    // test asserted /dashboard and failed on every run. Drive the real
    // sign-in via the shared `login` helper, which gates on
    // form[data-hydrated="true"], fills the seeded student credentials,
    // couples the click to the auth POST, and asserts the /dashboard
    // redirect strictly.
    await login(page, "student");
    await expect(page.getByRole("heading", { name: /Welcome/i })).toBeVisible();
  });
});
