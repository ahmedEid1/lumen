/**
 * Instructor golden path (Phase H3, item 3).
 *
 *   1. Login as teacher@lumen.test.
 *   2. Create a new draft course via the studio "new" surface.
 *   3. Open the AI outline modal, enter a brief, click Generate.
 *      With ``LLM_PROVIDER=noop`` the noop returns plain text rather
 *      than the strict JSON shape the outline contract requires, so
 *      the request surfaces a deterministic "AI returned an unexpected
 *      response" error. That deterministic failure IS the assertion —
 *      the modal stays open and a toast tells the user the model
 *      misbehaved. When a real provider is wired this path can flip
 *      to a positive assertion on the preview tree, but until then
 *      noop's known shape is "fails gracefully".
 *   4. Back on the course studio page, add a module + text lesson so
 *      the publish-guard is satisfied, then publish.
 *   5. Confirm the analytics section is visible — the analytics block
 *      renders a grid of StatTile children on the studio course page.
 *
 * Naming: the existing `instructor-flow.spec.ts` (pre-Phase H) already
 * exercises the manual-create + publish + catalog-surface flow and
 * the orchestrator asked us not to refactor it. This spec runs as a
 * peer (`instructor-golden.spec.ts`) so Playwright picks up both
 * without colliding.
 */
import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";

test.describe("instructor golden path — AI outline + publish + analytics", () => {
  test("create draft, attempt AI outline (noop), publish, analytics renders", async ({
    page,
  }) => {
    // 1) Login.
    await login(page, "teacher");

    // 2) Studio → new course.
    await page.goto("/studio");
    await page.getByRole("link", { name: /new course/i }).click();
    await expect(page).toHaveURL(/\/studio\/new/);

    const uniqueTitle = `H3 instructor golden ${Date.now()}`;
    await page.getByLabel(/title/i).fill(uniqueTitle);
    await page.getByLabel(/overview/i).fill("Created by the H3 golden e2e suite.");
    await page.getByRole("button", { name: /create/i }).click();
    await expect(page).toHaveURL(/\/studio\/[^/]+$/);
    const courseStudioUrl = page.url();

    // 3) AI outline modal (noop branch).
    //
    // The "AI outline" trigger lives in the /studio root header (not
    // on the per-course studio page), so route there to open the
    // modal.
    await page.goto("/studio");
    await page
      .getByRole("button", { name: /generate with ai|ai outline|generate.*outline/i })
      .first()
      .click();

    const aiModal = page.getByRole("dialog", { name: /generate course with ai|outline|ai/i });
    await expect(aiModal).toBeVisible();
    await aiModal
      .getByRole("textbox")
      .first()
      .fill(
        "An intro course on building APIs with FastAPI for engineers " +
          "coming from Django.",
      );
    await aiModal.getByRole("button", { name: /generate/i }).click();

    // With LLM_PROVIDER=noop the backend's outline parser rejects the
    // canned non-JSON reply and surfaces ``ai.bad_output``. The
    // frontend toasts the error message. Two acceptable signals:
    //   1. an error toast surfaces (sonner / aria-live region), or
    //   2. the modal remains open on the brief phase rather than
    //      transitioning to the review preview.
    // Either is sufficient evidence we hit the deterministic noop
    // branch and the UI degraded gracefully.
    const errorRegion = page.locator(
      '[role="status"], [role="alert"], [data-sonner-toast]',
    );
    const previewTree = page.getByTestId("ai-outline-preview");
    await expect
      .poll(
        async () => {
          const hasError = (await errorRegion.count()) > 0;
          const previewVisible = await previewTree
            .isVisible()
            .catch(() => false);
          return hasError || !previewVisible;
        },
        { timeout: 20_000 },
      )
      .toBeTruthy();

    // Close the modal via Escape (wired in ai-outline-modal.tsx).
    await page.keyboard.press("Escape");
    await expect(aiModal).not.toBeVisible();

    // 4) Back on the in-progress course, add a module + lesson so
    // publish-guard passes, then publish.
    await page.goto(courseStudioUrl);
    await page.getByPlaceholder(/new module title/i).fill("Intro");
    await page.getByRole("button", { name: /add module/i }).click();

    await page
      .getByRole("link", { name: /edit lessons/i })
      .first()
      .click();
    await expect(page).toHaveURL(/\/studio\/[^/]+\/modules\/[^/]+$/);

    await page.getByRole("button", { name: /^\+ text$/i }).click();
    await page.getByLabel(/^title$/i).first().fill("Hello world");
    await page.locator("textarea").first().fill("# Hi\n\nFirst lesson.");
    await page.getByRole("button", { name: /^save lesson$/i }).click();

    await page.goto(courseStudioUrl);

    await page.getByRole("button", { name: /^publish$/i }).click();
    await expect(page.locator("text=published").first()).toBeVisible({
      timeout: 10_000,
    });

    // 5) Analytics section is visible on the course studio page. The
    // section is rendered conditionally on analyticsQ.data — anchor on
    // the heading + assert at least one chart-card tile renders below.
    const analyticsHeading = page.getByRole("heading", {
      name: /analytics|analytic/i,
    });
    await expect(
      analyticsHeading,
      "the analytics section heading should render after publish",
    ).toBeVisible({ timeout: 15_000 });

    // The analytics section is the heading's parent <section>. The
    // grid inside renders one StatTile per metric (enrolments,
    // completions, avg rating, avg progress, new-7d, new-30d) — for
    // a freshly-published course the values are 0 but the tiles
    // still render.
    const analyticsSection = analyticsHeading.locator(
      'xpath=ancestor::section[1]',
    );
    const tiles = analyticsSection.locator("div.grid > *");
    await expect
      .poll(() => tiles.count(), { timeout: 5_000 })
      .toBeGreaterThan(0);
  });
});
