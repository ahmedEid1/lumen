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
    // Login form is prefilled with seeded demo credentials.
    await page.getByRole("button", { name: /Sign in/i }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("heading", { name: /Welcome/i })).toBeVisible();
  });
});
