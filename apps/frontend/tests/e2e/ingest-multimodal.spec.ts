/**
 * Multi-modal ingest golden path (Phase H3, item 5).
 *
 *   1. Login as teacher@lumen.test.
 *   2. Open the studio, click the "Import from URL" CTA, paste a
 *      known YouTube URL.
 *   3. Click Preview — the modal should render the source detection
 *      badge ("YouTube") and a preview tree with at least one module
 *      and one lesson.
 *   4. Click Commit — the modal closes, navigation lands on the new
 *      draft course's studio page, and the draft appears in the
 *      instructor's drafts filter on /studio.
 *
 * URL source: ideally we read the first record from
 * ``apps/backend/evals/ingest/dataset.jsonl`` (H2 produces this).
 * The eval suite is in flight in parallel; this spec falls back to a
 * hard-coded TED talk URL if the dataset isn't there yet. Both points
 * at a public YouTube video so the regex-based source-detection
 * branch fires and the preview tree renders.
 *
 * Caveat: the ingest pipeline hits youtube-transcript-api for the
 * actual transcript fetch, which is rate-limited per IP. In CI we
 * may see a 429 or a "no transcript available" error — the spec
 * treats either as a hard failure with a clear message so the
 * operator can decide whether to retry or update the URL.
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { login } from "./helpers/login";

// Fallback URL — TED's "How to spot a misleading graph" (8 minutes,
// has public English transcript, low risk of upstream changes).
const FALLBACK_YOUTUBE_URL = "https://www.youtube.com/watch?v=E91bGT9BjYk";

function pickIngestUrl(): string {
  // The eval suite lives at apps/backend/evals/ingest/dataset.jsonl
  // relative to the repo root. Playwright's cwd depends on where the
  // test runner was launched — usually `apps/frontend` (via the
  // pnpm filter) but the repo root works too. Cover both shapes.
  const candidatePaths = [
    resolve(process.cwd(), "../../apps/backend/evals/ingest/dataset.jsonl"),
    resolve(process.cwd(), "../backend/evals/ingest/dataset.jsonl"),
    resolve(process.cwd(), "apps/backend/evals/ingest/dataset.jsonl"),
  ];
  for (const path of candidatePaths) {
    if (!existsSync(path)) continue;
    try {
      const firstLine = readFileSync(path, "utf-8").split("\n")[0]?.trim();
      if (!firstLine) continue;
      const row = JSON.parse(firstLine) as { url?: string };
      if (typeof row.url === "string" && row.url.includes("youtube")) {
        return row.url;
      }
    } catch {
      // ignore parse errors and fall through to fallback
    }
  }
  return FALLBACK_YOUTUBE_URL;
}

test.describe("multi-modal ingest golden path", () => {
  // fixme: depends on a live YouTube transcript fetch from inside the api
  // container (apps/backend/app/services/content_ingest.py:181 calls the
  // youtube-transcript-api library). YouTube actively blocks GitHub-hosted
  // CI runner IPs and the fallback / dataset URLs go in and out of having
  // transcripts; the test is structurally sound but the upstream signal
  // isn't a reliable CI gate. Two paths to re-green this:
  //   1. add an `INGEST_PROVIDER=fixture` mode that reads a canned
  //      transcript fixture from disk when env says so (mirroring
  //      LLM_PROVIDER=noop / EMBEDDING_PROVIDER=noop), and pin that in
  //      e2e.yml's .env overrides
  //   2. or pin a private corporate-owned video with stable captions and
  //      proxy the transcript fetch through a backend route
  // Until either lands, run this manually against the live AWS box with
  // `pnpm exec playwright test ingest-multimodal --project=chromium`.
  test.fixme("paste YouTube URL → preview → commit → draft listed", async ({
    page,
  }) => {
    // 1) Login.
    await login(page, "teacher");

    // 2) Studio → Import button.
    await page.goto("/studio");
    // The import button accessible name comes from
    // studio.import.button — match a tolerant regex so a localised
    // copy change doesn't break us.
    await page
      .getByRole("button", { name: /import|ingest|from url/i })
      .first()
      .click();

    const dialog = page.getByRole("dialog", {
      name: /import course from url|import/i,
    });
    await expect(dialog).toBeVisible();

    // 3) Paste a URL and click Preview. The label copy
    // ("Source URL" in EN) anchors on the /url/i fragment which
    // survives translation rotation.
    const url = pickIngestUrl();
    await dialog.getByLabel(/url/i).fill(url);

    // The "Detected: YouTube" badge updates from the local regex
    // detector before we click anything — assert it landed.
    await expect(
      dialog.locator("text=/youtube/i").first(),
      "source detection should flip the badge once a YouTube URL is pasted",
    ).toBeVisible({ timeout: 5_000 });

    await dialog.getByRole("button", { name: /preview/i }).click();

    // 4) Preview tree appears with at least one module + lesson. The
    // preview hits the live extractor which depends on the upstream
    // transcript API; bump the timeout so a slow fetch doesn't trip
    // a false failure.
    const moduleHeading = dialog.locator(
      'input[aria-label*="module" i], input[aria-label*="Module" i]',
    );
    await expect(moduleHeading.first()).toBeVisible({ timeout: 60_000 });

    // The footer renders a "Modules N · Lessons M" count line; both
    // numbers should be > 0 for a real YouTube transcript ingest.
    // Anchor on the commit button — its accessible name is
    // "Create draft course" (studio.import.commit). It's enabled iff
    // at least one lesson is present (totalLessons > 0).
    const commitBtn = dialog.getByRole("button", {
      name: /create draft course|^commit/i,
    });
    await expect(commitBtn).toBeEnabled({ timeout: 5_000 });

    // 5) Commit. The frontend creates a new draft course and routes
    // to /studio/<id> on success — wait for the URL change.
    await commitBtn.click();
    await expect(page).toHaveURL(/\/studio\/[^/]+$/, { timeout: 30_000 });

    // 6) Verify the draft appears on the studio drafts list. The
    // studio root surfaces a "Draft" tab with a count badge — after
    // commit, the count should be at least 1.
    await page.goto("/studio");
    const draftTab = page.getByRole("tab", { name: /draft/i });
    await expect(draftTab).toBeVisible();
    await draftTab.click();
    // The visible rows list draft courses; at least one row must be
    // present (we just committed one).
    const draftRows = page.locator("ul > li").filter({ has: page.locator("a") });
    await expect
      .poll(() => draftRows.count(), { timeout: 10_000 })
      .toBeGreaterThan(0);
  });
});
