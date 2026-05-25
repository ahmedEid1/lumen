/**
 * Auth golden path (Phase H3, item 1).
 *
 * Walks the full credentialed-user lifecycle end-to-end against the
 * live docker-compose stack:
 *
 *   1. Register a fresh user via /register.
 *   2. Confirm the verification email lands in Mailpit, extract the
 *      ?token=… from the link, hit /verify-email?token=… and assert
 *      the success copy.
 *   3. Hit /forgot-password, request a reset, confirm a second email
 *      lands, extract that token, walk through /reset-password?token=…
 *      and pick a new password.
 *   4. Log in with the new password and land on /dashboard.
 *
 * Why Mailpit rather than a backend dev endpoint: the spec for H3
 * calls this out explicitly (don't add a backend endpoint just for
 * tests — that's H6's territory). Mailpit is already in
 * docker-compose.yml (axllent/mailpit:v1.20) catching all SMTP from
 * the Celery worker, with a REST API on :8025. The reset + verify
 * email templates put the token in the link query string, so reading
 * the latest message body and pulling ?token= out is enough.
 *
 * Test isolation: the freshly-minted user's email is unique per run
 * (Date.now() suffix) so a re-run never collides with stale rows in
 * the DB. Mailpit's inbox is cleared in beforeAll so the poller can't
 * trip on a leftover envelope.
 */
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/login";
import {
  clearMailpit,
  extractTokenFromMessage,
  waitForMessage,
} from "./helpers/mailpit";

test.describe("auth golden path — register → verify → reset → login", () => {
  // We rely on a single, deterministic email throughout the chained
  // test() blocks so the verify + reset emails are inspectable in
  // order. The timestamp suffix keeps the value unique across runs.
  const stamp = Date.now();
  const email = `e2e-auth-${stamp}@lumen.test`;
  const initialPassword = "InitialPwd!12345";
  const resetPassword = "NewPwd!12345Reset";

  test.beforeAll(async () => {
    await clearMailpit();
  });

  test("register a fresh user and verify the email", async ({ page }) => {
    // 1) Register.
    await page.goto("/register");
    await page.getByLabel(/full name/i).fill("E2E Auth User");
    // Use the form locator to disambiguate from any "email/password"
    // label that bleeds into the navbar / locale switcher copy.
    await page.locator("form").getByLabel(/^email$/i).fill(email);
    await page.locator("form").getByLabel(/password/i).fill(initialPassword);
    await page
      .locator("form")
      .getByRole("button", { name: /create|sign up|register/i })
      .click();

    // Register currently redirects to /dashboard on success (auth
    // store auto-logs-in the new user). Verification is a separate
    // step the user can do from the email link.
    await expect(page).toHaveURL(/\/dashboard/);

    // 2) Pull the verification email from Mailpit.
    const message = await waitForMessage({
      to: email,
      subjectMatcher: /verify|confirm/i,
      timeoutMs: 20_000,
    });
    const token = extractTokenFromMessage(message, /\/verify-email\?token=/);

    // 3) Visit the verify page — the success state renders an
    // aria-live region with the success copy and a "Continue" button.
    await page.goto(`/verify-email?token=${encodeURIComponent(token)}`);
    await expect(
      page.getByRole("heading", { name: /verify email|email verification/i }),
    ).toBeVisible();
    // The success state surfaces a button labelled with the localised
    // continue copy. We assert the button shows up rather than relying
    // on a translation-bound regex.
    await expect(
      page.getByRole("button", { name: /continue|go to dashboard/i }),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("forgot password → reset → login with new password", async ({
    page,
  }) => {
    // 1) Request a reset.
    await page.goto("/forgot-password");
    await page.getByLabel(/email/i).fill(email);
    await page.getByRole("button", { name: /send|reset/i }).first().click();

    // 2) Pull the reset email.
    const message = await waitForMessage({
      to: email,
      subjectMatcher: /reset/i,
      timeoutMs: 20_000,
    });
    const token = extractTokenFromMessage(message, /\/reset-password\?token=/);

    // 3) Submit the new password.
    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`);
    await page.getByLabel(/password/i).fill(resetPassword);
    await page
      .locator("form")
      .getByRole("button", { name: /reset|submit|update/i })
      .click();
    // After a successful reset we redirect to /login.
    await expect(page).toHaveURL(/\/login/);

    // 4) Log in with the new password — sanity-check the new
    // credential actually works.
    await loginAs(page, email, resetPassword);
    await expect(page).toHaveURL(/\/dashboard/);
  });
});
