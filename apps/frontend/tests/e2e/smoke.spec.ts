import { test, expect } from "@playwright/test";

test.describe("smoke", () => {
  test("home page loads with hero", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /Learn anything/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /Browse courses/i })).toBeVisible();
  });

  test("can navigate to catalog", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /Catalog/i }).first().click();
    await expect(page).toHaveURL(/\/courses/);
    await expect(page.getByRole("heading", { name: /Catalog/i })).toBeVisible();
  });

  test("student signs in and reaches dashboard", async ({ page }) => {
    await page.goto("/login");
    // Iter 101: the navbar's "Sign in" link contains a button with
    // the same accessible name as the form's submit, so an unscoped
    // getByRole('button') trips strict mode. Scope to the form
    // element so we always pick the submit button.
    await page.locator("form").getByRole("button", { name: /Sign in/i }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("heading", { name: /Welcome/i })).toBeVisible();
  });
});
