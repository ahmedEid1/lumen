/**
 * Screenshot capture for the README + portfolio hero pack (A5).
 *
 * Runs against the locally seeded stack (`make seed`, see
 * `apps/backend/app/seeds/agentic_demo.py`). Captures five PNGs into
 * `docs/screenshots/` at a fixed 1440x900 viewport:
 *
 *   - hero.png            — learner agent-trace drill-down (Surface
 *                           A) — the "show me how you got this"
 *                           full-page surface with retrieval + tool
 *                           calls + cost badge populated. This is
 *                           the recruiter's first-30-seconds shot.
 *   - trace-timeline.png  — same surface, scrolled to the timeline.
 *   - studio-replay.png   — instructor self-critique replay
 *                           (Surface B), `/studio/draft/{id}/replay`.
 *   - observability.png   — `/admin/observability` admin dashboard.
 *   - evals.png           — `/admin/evals` admin dashboard.
 *
 * IDs are looked up at runtime from the API (we know which slugs the
 * seed creates) so a re-seed with a different nanoid still works.
 *
 * Animations are disabled via `prefers-reduced-motion: reduce` on the
 * browser context. Replay auto-advance is paused with a fixed-delay
 * wait before capture so the lime-active row is always the same.
 *
 * NOTE this spec uses an absolute path *only* for the screenshot
 * output: it writes to `<repo-root>/docs/screenshots/<name>.png`,
 * resolved off the spec file's location (`__dirname`). Everywhere
 * else, the spec uses relative routes via `page.goto(...)`.
 */
import { test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { login } from "./helpers/login";

// ESM-safe equivalent of CommonJS `__dirname`. Playwright runs this
// spec as an ES module so `__dirname` is undefined; deriving it from
// `import.meta.url` works in both `pnpm exec playwright test` (host)
// and inside the `docker compose --profile e2e run e2e` container.
const __dirname_esm = path.dirname(fileURLToPath(import.meta.url));

// Fixed viewport for every shot. Matches the README hero target's
// 1440x900 aspect; downscaling on retina is the caller's concern.
const VIEWPORT = { width: 1440, height: 900 } as const;

// Output dir — captures land here and the runner moves them into
// `docs/screenshots/` after the run.
//
// The `e2e` profile binds `./apps/frontend:/work` only, so the spec
// can't write *above* `/work` without an extra mount. We therefore
// write under `/work/.screenshots-tmp` (= `apps/frontend/.screenshots-tmp`
// on the host) by default. The operator runbook in
// `docs/release/_activation_a5.md` documents the `mv` step.
//
// Set `LUMEN_SCREENSHOT_DIR=/absolute/path` to override (e.g. when
// running `pnpm exec playwright test` directly on the host with
// Playwright browsers installed).
const SCREENSHOT_DIR =
  process.env.LUMEN_SCREENSHOT_DIR ??
  path.resolve(__dirname_esm, "..", "..", ".screenshots-tmp");

test.use({
  viewport: VIEWPORT,
  // Disable CSS animations + reduce motion so screenshots are stable.
  contextOptions: { reducedMotion: "reduce" },
});

/**
 * Look up the (conversation_id, message_id) pair the agentic-demo
 * seed wrote against the student. We hit the public courses endpoint
 * to find the FastAPI course id, then the /me/tutor endpoint to find
 * the conversation. Falls back to scanning the dashboard's link list
 * if the API surface isn't quite shaped that way.
 */
async function lookupTutorIds(page: Page): Promise<{
  conversationId: string;
  messageId: string;
}> {
  // We're already logged-in via the caller; the conversation list
  // endpoint scopes by the auth cookie.
  //
  // The course detail endpoint accepts slug-or-id, so we hit it
  // directly with the known seed slug rather than scanning the
  // catalog. The shape is CourseDetail, not Page<...>.
  const courseRes = await page.request.get(
    "/api/v1/courses/fastapi-from-zero",
  );
  if (!courseRes.ok()) {
    throw new Error(
      `course lookup failed (${courseRes.status()}): ${await courseRes.text()}`,
    );
  }
  const course = (await courseRes.json()) as { id: string; slug: string };
  if (course.slug !== "fastapi-from-zero") {
    throw new Error(`course lookup returned wrong slug: ${course.slug}`);
  }
  const convRes = await page.request.get(
    `/api/v1/courses/${course.id}/tutor/conversations`,
  );
  if (!convRes.ok()) {
    throw new Error(
      `tutor conversation listing failed (${convRes.status()}): ${await convRes.text()}`,
    );
  }
  // The listing endpoint returns a Page<TutorConversationSummary>;
  // the items are already ordered newest-touched first.
  const convPage = (await convRes.json()) as {
    items: Array<{ id: string; last_message_at: string }>;
  };
  if (!convPage.items || convPage.items.length === 0) {
    throw new Error(
      "no seeded tutor conversation found — did `make seed` run?",
    );
  }
  const conv = convPage.items[0];
  // The detail endpoint is conversation-scoped (not course-scoped) —
  // `/tutor/conversations/{id}` returns messages directly.
  const detailRes = await page.request.get(
    `/api/v1/tutor/conversations/${conv.id}`,
  );
  if (!detailRes.ok()) {
    throw new Error(
      `tutor conversation detail failed (${detailRes.status()}): ${await detailRes.text()}`,
    );
  }
  const detail = (await detailRes.json()) as {
    messages: Array<{ id: string; role: string }>;
  };
  const assistantMsg = detail.messages.find((m) => m.role === "assistant");
  if (!assistantMsg) {
    throw new Error("no assistant turn in the seeded conversation");
  }
  return { conversationId: conv.id, messageId: assistantMsg.id };
}

/**
 * Look up the draft course id. The agentic_demo seed creates one
 * course with slug `ai-tutor-design-patterns` in status=draft owned
 * by teacher@lumen.test.
 */
async function lookupDraftCourseId(page: Page): Promise<string> {
  // The course detail endpoint takes slug-or-id and returns the row
  // regardless of status when the caller is the owner (or admin).
  const res = await page.request.get(
    "/api/v1/courses/ai-tutor-design-patterns",
  );
  if (!res.ok()) {
    throw new Error(
      `draft-course lookup failed (${res.status()}): ${await res.text()}`,
    );
  }
  const body = (await res.json()) as { id: string; slug: string };
  if (body.slug !== "ai-tutor-design-patterns") {
    throw new Error(
      `draft lookup returned wrong slug: ${body.slug}`,
    );
  }
  return body.id;
}

test.describe("A5 — README hero + portfolio screenshot pack", () => {
  test("hero + trace timeline (learner-facing)", async ({ page }) => {
    await login(page, "student", { rescueRedirect: true });
    const ids = await lookupTutorIds(page);

    await page.goto(`/dashboard/tutor/${ids.conversationId}/turn/${ids.messageId}`);
    // Wait for the timeline + cost badge to land before capture.
    await page.locator('[data-testid="trace-timeline"]').waitFor({
      state: "visible",
      timeout: 30_000,
    });
    // Brief settle for fonts / images.
    await page.waitForTimeout(800);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "hero.png"),
      fullPage: false,
    });

    // Second shot focuses on the timeline + retrieval audits below
    // the cost badge. We scroll by a fixed offset rather than using
    // a text selector — the i18n copy on the "step-by-step" label
    // is a brittle hook in CI.
    await page.evaluate(() => window.scrollBy(0, 360));
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "trace-timeline.png"),
      fullPage: false,
    });
  });

  test("studio replay (instructor self-critique)", async ({ page }) => {
    await login(page, "teacher", { rescueRedirect: true });
    const draftCourseId = await lookupDraftCourseId(page);

    await page.goto(`/studio/draft/${draftCourseId}/replay`);
    // Replay auto-plays; wait for the controls + a step card to land,
    // then pause the playback so the captured shot is deterministic.
    await page.locator('[data-testid="trace-timeline"]').waitFor({
      state: "visible",
      timeout: 30_000,
    });
    // Click the toggle once to pause if it's playing. The button's
    // aria-label flips between "Pause replay" and "Play replay".
    const pauseBtn = page.getByRole("button", { name: /pause replay/i });
    if (await pauseBtn.isVisible().catch(() => false)) {
      await pauseBtn.click();
    }
    // Scrub to roughly the middle so the lime-active row sits in
    // frame next to the controls.
    const scrub = page.locator('[data-testid="replay-scrub"]');
    if (await scrub.isVisible().catch(() => false)) {
      await scrub.evaluate((el: HTMLInputElement) => {
        el.value = "3";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    await page.waitForTimeout(600);

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "studio-replay.png"),
      fullPage: false,
    });
  });

  test("admin observability + evals dashboards", async ({ page }) => {
    await login(page, "admin", { rescueRedirect: true });

    // ---- Observability ----
    //
    // The H7 dashboard renders three tabs (Celery / LLM traces /
    // Retrieval quality). The default Celery tab needs a couple of
    // seconds for the worker health poll to come back; we land on
    // the "LLM traces" tab instead because that's the more visually
    // dense surface — and we seeded llm_calls + agent_traces rows
    // so it'll actually have content.
    await page.goto("/admin/observability");
    await page
      .locator("h1, h2")
      .first()
      .waitFor({ state: "visible", timeout: 30_000 });
    const llmTracesTab = page.getByRole("tab", { name: /llm traces/i });
    if (await llmTracesTab.isVisible().catch(() => false)) {
      await llmTracesTab.click();
    } else {
      // Fall back to clicking a button or link with the same label.
      const llmBtn = page.getByText(/llm traces/i).first();
      if (await llmBtn.isVisible().catch(() => false)) {
        await llmBtn.click();
      }
    }
    // Give the tab content time to fetch + render.
    await page.waitForTimeout(2_000);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "observability.png"),
      fullPage: false,
    });

    // ---- Evals ----
    await page.goto("/admin/evals");
    await page
      .locator("h1, h2")
      .first()
      .waitFor({ state: "visible", timeout: 30_000 });
    // Let the suite-card grid finish loading the latest-report data.
    await page.waitForTimeout(1_500);
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "evals.png"),
      fullPage: false,
    });
  });
});
