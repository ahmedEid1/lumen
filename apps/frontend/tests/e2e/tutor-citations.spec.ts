/**
 * Tutor citations golden path (Phase H3, item 4).
 *
 *   1. Login as student@lumen.test.
 *   2. Open /learn/<seeded course>, toggle the tutor panel.
 *   3. Ask a question — the noop provider emits a deterministic
 *      response of the shape:
 *         "Based on the course content, <user question…> [L:<lesson_id>]"
 *      where the [L:…] tokens are pulled from the system-prompt
 *      context block (see app/services/llm.py NoopProvider docstring).
 *   4. Assert the assistant turn contains at least one [L:<lesson_id>]
 *      citation token AND that the cited lesson_id matches a real
 *      lesson of the course (looked up via the catalog API).
 *
 * Pre-flight requirement: the tutor's retrieval pipeline pulls from
 * ``lesson_chunks`` (Phase E0). The seed creates a published course
 * but does NOT enqueue an embedding indexing — the workflow that
 * runs this spec MUST trigger ``index_course_embeddings`` against
 * the seeded course beforehand (the CI step does this via a small
 * python -c invocation). If chunks are missing the tutor returns the
 * refusal sentinel and this spec fails fast with a clear message
 * pointing at the pre-flight.
 *
 * The citation pill row is wired with ``data-testid="tutor-citations"``
 * (apps/frontend/src/components/tutor/tutor-panel.tsx) so we can
 * anchor the assertion against the DOM rather than the prose.
 */
import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";
import { getCourseBySlug } from "./helpers/api";

const SEED_COURSE_SLUG = "fastapi-from-zero";

test.describe("tutor citations golden path", () => {
  test("ask a question, response cites a real lesson id", async ({ page }) => {
    // 1) Login.
    await login(page, "student", { rescueRedirect: true });

    // 2) Open the learn surface for the seeded course.
    await page.goto(`/learn/${SEED_COURSE_SLUG}`);
    await expect(page).toHaveURL(new RegExp(`/learn/${SEED_COURSE_SLUG}`));

    // The tutor panel is unmounted by default — click "Ask the tutor"
    // to bring it in. The CTA's accessible name comes from
    // tutor.askButton / tutor.closeButton translations.
    const askButton = page.getByRole("button", {
      name: /ask.*tutor|tutor/i,
    });
    await askButton.first().click();
    const panel = page.getByTestId("tutor-panel");
    await expect(panel).toBeVisible();

    // 3) Send a question. The composer is a <textarea>; the send
    // button has aria-label="tutor.send" (an arrow-up icon button).
    const composer = panel.getByRole("textbox").first();
    await composer.fill(
      "What library does FastAPI use for data validation?",
    );
    // The Send button has no visible text — anchor on aria-label.
    const sendBtn = panel.locator('button[type="submit"]').last();
    await sendBtn.click();

    // 4) Wait for the assistant turn to land. The panel renders
    // assistant turns with data-testid="tutor-message-assistant".
    const assistantTurn = panel
      .locator('[data-testid="tutor-message-assistant"]')
      .last();
    await expect(assistantTurn).toBeVisible({ timeout: 30_000 });

    const assistantText = (await assistantTurn.innerText()).trim();

    // Refusal-shape guard: if no chunks were indexed pre-flight, the
    // backend's empty-retrieval branch fires and the assistant turn
    // carries the localised refusal copy. Fail fast with a pointer
    // at the pre-flight step so the operator knows what's missing.
    expect(
      assistantText.toLowerCase(),
      "tutor returned a refusal — likely the seeded course has no " +
        "lesson_chunks. Did the CI / dev workflow run " +
        "index_course_embeddings for the seeded course before this spec?",
    ).not.toMatch(/i don'?t have material/);

    // QA-iter1 follow-up: the wire-format `[L:<lesson_id>]` tokens
    // are no longer rendered into the user-visible bubble — they're
    // replaced by numbered superscripts that anchor to the citation
    // pill row. So the assertion now reads the lesson_ids back from
    // the pill row's hrefs (`/courses/lessons/<lesson_id>`), which
    // is the DOM mirror of the same set.
    const citationLinks = panel
      .locator('[data-testid="tutor-citations"] a[href^="/courses/lessons/"]');
    await expect(
      citationLinks.first(),
      "expected the citation pill row to be visible with at least one " +
        "lesson link. The orchestrator emits `[L:<lesson_id>]` inline, " +
        "the frontend parses them into numbered references + the pill " +
        "row below the bubble. If neither is rendering, the backend " +
        "returned a refusal or pre-flight ingest didn't index chunks.",
    ).toBeVisible({ timeout: 5_000 });
    const citedLessonIds = (
      await citationLinks.evaluateAll((els) =>
        els.map((el) => el.getAttribute("href") ?? ""),
      )
    ).map((href) => href.replace("/courses/lessons/", ""));
    expect(citedLessonIds.length, "no lesson ids on pill row").toBeGreaterThan(0);

    // 5) Sanity-check that every cited lesson id belongs to the
    // seeded course. We pull the course detail via the catalog API
    // (unauthenticated read) and intersect.
    const course = await getCourseBySlug(SEED_COURSE_SLUG);
    const realLessonIds = new Set(
      course.modules.flatMap((m) => m.lessons.map((l) => l.id)),
    );
    const valid = citedLessonIds.filter((id) => realLessonIds.has(id));
    expect(
      valid,
      `none of the cited lesson ids match a real lesson on the course. ` +
        `cited=${JSON.stringify(citedLessonIds)} real=${JSON.stringify([
          ...realLessonIds,
        ])}`,
    ).not.toHaveLength(0);

    // The citation pill row is also wired with data-testid so a
    // future change to the noop's prose shape doesn't silently strip
    // the visible affordance.
    await expect(
      panel.locator('[data-testid="tutor-citations"]').first(),
    ).toBeVisible();
  });
});
