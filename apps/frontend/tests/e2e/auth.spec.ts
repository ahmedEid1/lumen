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
 * One `test()` block, not two: Playwright re-imports the spec file
 * for every worker process and every retry, so a `const stamp =
 * Date.now()` at describe scope produces DIFFERENT timestamps in
 * different workers. If we split register and forgot-password across
 * two `test()` blocks, worker A registers `e2e-auth-<T1>` while
 * worker B (or a retry) requests a reset for `e2e-auth-<T2>` — an
 * email that was never registered. The backend silently returns 200
 * to avoid email-enumeration, no reset email is enqueued, and the
 * mailpit poller times out at 20s. Folding both halves into one
 * test keeps `email` in a single closure across the full lifecycle.
 */
import { expect, test } from "@playwright/test";
import { loginAs, preDismissOnboarding } from "./helpers/login";
import {
  clearMailpit,
  extractTokenFromMessage,
  waitForMessage,
} from "./helpers/mailpit";

test.describe("auth golden path — register → verify → reset → login", () => {
  test.beforeAll(async () => {
    await clearMailpit();
  });

  test("register → verify → reset → login with new password", async ({
    page,
  }) => {
    // Per-test (not per-describe) stamp + email. See the file-level
    // docstring for why this can't live at describe scope.
    const stamp = Date.now();
    const email = `e2e-auth-${stamp}@lumen.test`;
    const initialPassword = "InitialPwd!12345";
    const resetPassword = "NewPwd!12345Reset";

    await preDismissOnboarding(page);

    // 1) Register.
    await page.goto("/register");
    await page.getByLabel(/full name/i).fill("E2E Auth User");
    // Use the form locator to disambiguate from any "email/password"
    // label that bleeds into the navbar / locale switcher copy.
    await page.locator("form").getByLabel(/^email$/i).fill(email);
    await page.locator("form").getByLabel("Password", { exact: true }).fill(initialPassword);
    // Loop 15 added a required confirm-password field + T&C checkbox.
    // Without both, canSubmit stays false and clicking the disabled
    // "Create account" button is a no-op.
    await page
      .locator("form")
      .getByLabel(/confirm password/i)
      .fill(initialPassword);
    // Radix Checkbox renders as role="checkbox" (button-backed, not
    // a native input). Click it directly via role; label-for-button
    // bubbling doesn't fire reliably under Playwright.
    await page.getByRole("checkbox", { name: /I agree to the/i }).click();
    await page
      .locator("form")
      .getByRole("button", { name: /create|sign up|register/i })
      .click();

    // Register currently redirects to /dashboard on success (auth
    // store auto-logs-in the new user). Verification is a separate
    // step the user can do from the email link.
    await expect(page).toHaveURL(/\/dashboard/);

    // 2) Pull the verification email from Mailpit.
    const verifyMessage = await waitForMessage({
      to: email,
      subjectMatcher: /verify|confirm/i,
      timeoutMs: 20_000,
    });
    const verifyToken = extractTokenFromMessage(
      verifyMessage,
      /\/verify-email\?token=/,
    );

    // 3) Visit the verify page — the success state renders an
    // aria-live region with the success copy and a "Continue" button.
    // Heading regex tolerates the actual i18n copy "Verify your email"
    // (verifyEmail.title) — earlier `/verify email|email verification/i`
    // didn't match because of the "your" interpolation. `/verify/i`
    // is enough to assert we landed on the right route.
    await page.goto(`/verify-email?token=${encodeURIComponent(verifyToken)}`);
    await expect(
      page.getByRole("heading", { name: /verify/i }),
    ).toBeVisible();
    // The success state surfaces a button labelled with the localised
    // continue copy. We assert the button shows up rather than relying
    // on a translation-bound regex.
    await expect(
      page.getByRole("button", { name: /continue|go to dashboard/i }),
    ).toBeVisible({ timeout: 10_000 });

    // 4) Forgot-password — request a reset for the same email.
    await page.goto("/forgot-password");
    await page.getByLabel(/email/i).fill(email);
    await page.getByRole("button", { name: /send|reset/i }).first().click();

    // 5) Pull the reset email.
    const resetMessage = await waitForMessage({
      to: email,
      subjectMatcher: /reset/i,
      timeoutMs: 20_000,
    });
    const resetToken = extractTokenFromMessage(
      resetMessage,
      /\/reset-password\?token=/,
    );

    // 6) Submit the new password. Button regex includes /set/i — the
    // actual i18n copy is "Set new password" (auth.reset.submit), which
    // didn't match the original /reset|submit|update/i and let
    // Playwright spin for the whole 60s actionTimeout before failing.
    await page.goto(`/reset-password?token=${encodeURIComponent(resetToken)}`);
    await page.getByLabel("Password", { exact: true }).fill(resetPassword);
    await page
      .locator("form")
      .getByRole("button", { name: /set|reset|submit|update/i })
      .click();
    // After a successful reset we redirect to /login.
    await expect(page).toHaveURL(/\/login/);

    // 7) Log in with the new password — sanity-check the new
    // credential actually works.
    await loginAs(page, email, resetPassword);
    await expect(page).toHaveURL(/\/dashboard/);
  });
});
