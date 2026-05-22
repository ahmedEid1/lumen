/**
 * Learner golden path (Phase H3, item 2).
 *
 *   1. Login as student@lumen.test.
 *   2. Browse the catalog and land on the seeded course.
 *   3. Enrol (no-op if seed already enrolled the student).
 *   4. Open /learn/[slug], walk through every lesson clicking
 *      "Mark complete" — for the quiz lesson we pick the documented
 *      correct answer so the quiz lesson actually progresses.
 *   5. Back on the dashboard, the completed-enrollments section
 *      surfaces the Open Badge + certificate links (both wired to
 *      /api/v1/credentials/{id} and /api/v1/certificates/{id}.pdf).
 *
 * Seed truth (apps/backend/app/cli.py):
 *   slug:  fastapi-from-zero
 *   modules: 3   (Getting started, Routing & schemas, Persistence)
 *   lessons: 5   (4 text + 1 quiz). The quiz's correct answer key
 *                is "b" — the question "Which library provides
 *                FastAPI's data validation?" with the right pick
 *                being "pydantic".
 *
 * The pre-existing learner-journey.spec.ts already covers a short
 * version of this flow (login → enrol → complete first lesson). This
 * spec extends it to cover the *credential surface* — the visible end
 * state after the learner finishes a full course.
 */
import { expect, test, type Page } from "@playwright/test";
import { login } from "./helpers/login";

const SEED_COURSE_SLUG = "fastapi-from-zero";

async function markCurrentLessonComplete(page: Page): Promise<void> {
  // The text-lesson player exposes a "Mark complete" button at the
  // bottom of the player column. After click, the learn page advances
  // to the next lesson (or stays put on the last). Either way the
  // button vanishes from the *current* lesson so we don't accidentally
  // double-click.
  const markBtn = page.getByRole("button", { name: /mark complete/i });
  if (await markBtn.isVisible().catch(() => false)) {
    await markBtn.click();
  }
}

async function submitQuizIfPresent(page: Page): Promise<void> {
  // The quiz lesson renders one MCQ ("Which library provides
  // FastAPI's data validation?") with three choice buttons. Seed
  // marks "pydantic" as the correct answer (answer_keys=["b"]).
  // The quiz player uses <button> elements, not <input type="radio">,
  // so we anchor on the visible "pydantic" label.
  //
  // The "Submit quiz" button is only present on quiz lessons — both
  // the choice click and the submit click are guarded by isVisible
  // so this helper is a no-op on text lessons.
  const submitBtn = page.getByRole("button", { name: /submit quiz/i });
  if (!(await submitBtn.isVisible().catch(() => false))) return;
  const pydanticOption = page.getByRole("button", { name: /^pydantic$/i });
  if (await pydanticOption.isVisible().catch(() => false)) {
    await pydanticOption.click();
  }
  await submitBtn.click();
}

test.describe("learner golden path", () => {
  test("enrol, complete every lesson, see Open Badge + certificate", async ({
    page,
  }) => {
    // 1) Login.
    await login(page, "student");

    // 2) Catalog → seeded course detail page.
    await page.goto(`/courses/${SEED_COURSE_SLUG}`);
    await expect(page).toHaveURL(new RegExp(`/courses/${SEED_COURSE_SLUG}`));

    // 3) Enrol if a CTA is offered. The seed already enrols the
    // student in the FastAPI course, so this branch is usually a no-op
    // — but keeping it makes the spec robust against a future
    // unseeded student.
    const enrollBtn = page.getByRole("button", { name: /^enroll$/i });
    if (await enrollBtn.isVisible().catch(() => false)) {
      await enrollBtn.click();
      await expect(
        page.getByRole("link", { name: /(continue|start) learning/i }),
      ).toBeVisible({ timeout: 10_000 });
    }

    // 4) Walk the learn surface and complete each lesson.
    await page.goto(`/learn/${SEED_COURSE_SLUG}`);
    await expect(page).toHaveURL(new RegExp(`/learn/${SEED_COURSE_SLUG}`));

    // Read the lesson outline from the nav — each lesson is a
    // <button> in the sticky aside. Iterate by visible text rather
    // than index so a reorder doesn't break us.
    const lessonButtons = page.getByRole("button").filter({
      // The outline lessons render as full-width buttons with a
      // truncated title span; matching the wrapper button by label
      // is brittle, so we anchor on the nav element instead.
      has: page.locator("span.truncate"),
    });

    // We don't iterate the buttons directly — instead, walk the
    // canonical "next" path until the player offers no more lessons.
    // Hard-cap iterations at 12 so a regression that loops forever
    // fails fast instead of timing out the test.
    for (let i = 0; i < 12; i++) {
      await submitQuizIfPresent(page);
      await markCurrentLessonComplete(page);

      const nextBtn = page.getByRole("button", { name: /^next$/i });
      const nextVisible = await nextBtn.isVisible().catch(() => false);
      const nextDisabled = nextVisible
        ? await nextBtn.isDisabled().catch(() => true)
        : true;
      if (!nextVisible || nextDisabled) break;
      await nextBtn.click();
    }
    // Silence the unused-locator warning — we intentionally only use
    // the outline for documentation, the loop walks via the next-button
    // path which is what a learner actually clicks.
    void lessonButtons;

    // 5) Back on the dashboard, the completed section surfaces the
    // certificate + Open Badge links. The dashboard renders Open
    // Badge as an /api/v1/credentials/{id} link and the cert PDF as
    // /api/v1/certificates/{course_id}.pdf.
    await page.goto("/dashboard");
    const certLink = page.locator(
      'a[href^="/api/v1/certificates/"][href$=".pdf"]',
    );
    const openBadgeLink = page.locator('a[href^="/api/v1/credentials/"]');
    // The completed-courses list only renders once the enrollment is
    // 100% complete; if any lesson silently failed to mark, we want
    // a clear assertion failure rather than a generic timeout.
    await expect(
      certLink.first(),
      "certificate PDF link should be on the dashboard after completing the seeded course",
    ).toBeVisible({ timeout: 10_000 });
    await expect(openBadgeLink.first()).toBeVisible();
  });
});
