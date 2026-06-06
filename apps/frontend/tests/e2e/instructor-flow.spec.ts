/**
 * Author: sign in, create a course, add a module + lesson, publish, and
 * confirm the owner-visible "published (private)" end state.
 *
 * W11 contract note: under the two-role rebuild (ADR-0026), `publish` keeps a
 * course PRIVATE — it does NOT list on the public catalog. Public listing now
 * requires a SEPARATE owner `Share` action *and* an explicit admin `approve`
 * (`is_publicly_listed` = public AND published AND approved AND not-deleted AND
 * not-quarantined, per app/services/visibility.py). The `Share` surface is
 * additionally gated behind FEATURE_PRIVATE_PUBLISH_ENABLED, which ships OFF
 * (existence-hidden) in the e2e stack. So the old "publish ⇒ visible on
 * /courses" tail was a STALE three-role-era expectation; the meaningful new
 * end state is the owner-visible published badge in the studio. We assert
 * that here (status badge swaps to "Published" + the course is listed in the
 * owner's studio "my courses" view), and verify the new private-publish
 * semantics via the publish toast copy ("Course published (private)…").
 *
 * Seeded creds: teacher@lumen.test / Teach!2026 (now role=user, ADR-0025).
 */
import { expect, test } from "@playwright/test";

import { login } from "./helpers/login";

// W11: Next.js App-Router SPA navigations (`<Link>` / router.push) emit a
// client-side pushState, not a fresh document load, so under cold-compile
// parallel pressure the URL can take >5s to settle — well past Playwright's
// default 5s `expect` ceiling (the global config lifts per-test/navigation/
// action timeouts but not `expect`). The login helper already polls
// toHaveURL with a generous window for exactly this; mirror that here for the
// in-app SPA hops so the flow isn't gated on the default 5s.
const NAV_TIMEOUT = 20_000;

test.describe("instructor flow", () => {
  test("create a course, add a lesson, publish, see the published state", async ({
    page,
  }) => {
    // W11: drive sign-in via the shared login() helper so the first-login
    // OnboardingTour overlay (`role=dialog`/`data-wb-dialog-overlay`,
    // full-viewport) never mounts — it was intercepting the navbar "Studio"
    // click and timing this test out on both browsers (the overlay, not the
    // catalog tail, is what actually failed). The helper preseeds the
    // onboarding-dismissed localStorage keys via addInitScript BEFORE any page
    // script runs, gates on form[data-hydrated], and couples the login POST
    // with the /dashboard redirect (rescueRedirect covers the SPA pushState
    // race under cold-compile parallel pressure).
    await login(page, "teacher", { rescueRedirect: true });

    // Studio.
    await page.getByRole("link", { name: /studio/i }).first().click();
    await expect(page).toHaveURL(/\/studio/, { timeout: NAV_TIMEOUT });

    // "New course". W11: the studio list is an App-Router client page whose
    // header <Link> can receive a click before React finishes hydrating it —
    // the click then no-ops (no pushState) and the URL never leaves /studio
    // (seen flaking on the first attempt). Retry the click until the SPA
    // navigation actually fires, then assert the destination.
    const newCourseLink = page.getByRole("link", { name: /new course/i });
    await expect(async () => {
      await newCourseLink.click();
      await expect(page).toHaveURL(/\/studio\/new/, { timeout: 5_000 });
    }).toPass({ timeout: NAV_TIMEOUT });

    const uniqueTitle = `E2E course ${Date.now()}`;
    await page.getByLabel(/title/i).fill(uniqueTitle);
    await page.getByLabel(/overview/i).fill("Created by the e2e suite.");
    await page.getByRole("button", { name: /create/i }).click();

    // Redirected to the studio detail page for the new course.
    await expect(page).toHaveURL(/\/studio\/[^/]+$/, { timeout: NAV_TIMEOUT });

    // Add a module.
    await page.getByPlaceholder(/new module title/i).fill("Intro");
    await page.getByRole("button", { name: /add module/i }).click();

    // Click into the module. Same App-Router <Link> hydration class as the
    // "New course" hop above — retry the click until the SPA nav fires.
    const editLessons = page.getByRole("link", { name: /edit lessons/i }).first();
    await editLessons.waitFor();
    await expect(async () => {
      await editLessons.click();
      await expect(page).toHaveURL(/\/studio\/[^/]+\/modules\/[^/]+$/, {
        timeout: 5_000,
      });
    }).toPass({ timeout: NAV_TIMEOUT });

    // Add a text lesson via the "Add lesson" buttons. W11 (stale-selector
    // fix): the "+" is now a decorative lucide <Plus> SVG icon (no aria-label),
    // not a literal "+" character, so it contributes nothing to the button's
    // accessible name — which is just the lesson-type label "text"
    // (lessonType.text). The old `/^\+ text$/i` regex therefore matched
    // nothing and the click hung the full action-timeout. Match the real
    // accessible name.
    await page.getByRole("button", { name: /^text$/i }).click();
    await page.getByLabel(/^title$/i).first().fill("Hello world");
    // Lesson body. W11 (stale-selector fix): the text-lesson body is no longer
    // a <textarea> — it is a Tiptap block editor (block-editor.tsx /
    // <EditorContent>), which renders a `[contenteditable="true"]` ProseMirror
    // surface (role=textbox). The old `page.locator("textarea")` matched
    // nothing for a text lesson, hanging the fill on the action-timeout. The
    // editor mounts client-side (immediatelyRender:false), so wait for the
    // contenteditable, click to focus, then type. The c2a833e save fix
    // serialises these blocks to body_markdown on save.
    const body = page.locator('[contenteditable="true"]').first();
    await body.waitFor();
    await body.click();
    await body.pressSequentially("First lesson body.");
    await page.getByRole("button", { name: /^save lesson$/i }).click();
    // Confirm the save landed (toast) before navigating away.
    await expect(page.getByText(/lesson saved/i)).toBeVisible({ timeout: 10_000 });

    // Back to course studio.
    await page.goto(page.url().replace(/\/modules\/[^/]+$/, ""));

    // Publish — the publish-guard requires at least one lesson, which we just
    // added. Under the new contract this transitions draft→published but keeps
    // the course PRIVATE (no public listing without Share + admin approve).
    await page.getByRole("button", { name: /^publish$/i }).click();

    // New-contract assertion #1: the success toast confirms the private
    // semantics ("Course published (private). Use Share to list it publicly.").
    await expect(page.getByText(/published \(private\)/i)).toBeVisible({
      timeout: 10_000,
    });

    // New-contract assertion #2: the status badge swaps to "Published"
    // (course.status.published). Scope to the header so we don't collide with
    // the toast copy above.
    await expect(
      page.getByRole("heading", { name: uniqueTitle }),
    ).toBeVisible();
    await expect(page.getByText("Published", { exact: true }).first()).toBeVisible();

    // New-contract assertion #3: the course is owner-visible in the studio
    // "my courses" list — the meaningful end state that replaces the stale
    // "visible on the public catalog" tail. (Public catalog listing needs a
    // separate Share + admin approve, and Share is flag-gated OFF in the e2e
    // stack, so it is out of scope for this flow.) Navigate via goto rather
    // than the navbar link so the lingering publish success-toast can't
    // intercept the click.
    await page.goto("/studio");
    await expect(page).toHaveURL(/\/studio$/, { timeout: NAV_TIMEOUT });
    await expect(
      page.getByRole("link", { name: uniqueTitle }),
    ).toBeVisible({ timeout: 10_000 });
  });
});
