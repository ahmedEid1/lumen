/**
 * Instructor: sign in, create a course, add a module + lesson, publish,
 * see it surface on the public catalog.
 *
 * Seeded creds: teacher@lumen.test / Teach!2026
 */
import { expect, test } from "@playwright/test";

test.describe("instructor flow", () => {
  test("create a course, add a lesson, publish, see it on the catalog", async ({
    page,
  }) => {
    // Sign in as the seeded instructor.
    await page.goto("/login");
    await page.getByLabel(/email/i).fill("teacher@lumen.test");
    await page.getByLabel(/password/i).fill("Teach!2026");
    // Iter 101: scope to the form (navbar Sign in link clashes).
    await page.locator("form").getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    // Studio.
    await page.getByRole("link", { name: /studio/i }).first().click();
    await expect(page).toHaveURL(/\/studio/);

    // "New course".
    await page.getByRole("link", { name: /new course/i }).click();
    await expect(page).toHaveURL(/\/studio\/new/);

    const uniqueTitle = `E2E course ${Date.now()}`;
    await page.getByLabel(/title/i).fill(uniqueTitle);
    await page.getByLabel(/overview/i).fill("Created by the e2e suite.");
    await page.getByRole("button", { name: /create/i }).click();

    // Redirected to the studio detail page for the new course.
    await expect(page).toHaveURL(/\/studio\/[^/]+$/);

    // Add a module.
    await page.getByPlaceholder(/new module title/i).fill("Intro");
    await page.getByRole("button", { name: /add module/i }).click();

    // Click into the module.
    await page.getByRole("link", { name: /edit lessons/i }).first().click();
    await expect(page).toHaveURL(/\/studio\/[^/]+\/modules\/[^/]+$/);

    // Add a text lesson via the "Add lesson" + Text button.
    await page.getByRole("button", { name: /^text$/i }).click();
    await page.getByLabel(/^title$/i).first().fill("Hello world");
    // Markdown body
    await page.locator("textarea").first().fill("# Hi\n\nFirst lesson.");
    await page.getByRole("button", { name: /^save$/i }).click();

    // Back to course studio.
    await page.goto(page.url().replace(/\/modules\/[^/]+$/, ""));

    // Publish — iter 43 requires at least one lesson, which we just added.
    await page.getByRole("button", { name: /^publish$/i }).click();
    // Status badge swaps to published.
    await expect(page.locator("text=published").first()).toBeVisible();

    // Browse to catalog as the same instructor (already signed in) and
    // confirm the new course is discoverable.
    await page.goto("/courses");
    await expect(page.locator(`text=${uniqueTitle}`).first()).toBeVisible({
      timeout: 10_000,
    });
  });
});
