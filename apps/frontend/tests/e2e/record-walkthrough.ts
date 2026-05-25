/**
 * record-walkthrough.ts — Autonomous Loom-replacement recorder.
 *
 * Drives a Chromium browser through Lumen's 6 demo beats with captioned
 * overlays at each step, captures the session as a .webm. The orchestrator
 * then muxes to .mp4 and commits as docs/screencast/walkthrough.mp4 — a
 * silent walkthrough that operators can ship as-is or re-record with
 * voiceover on Loom later (script: docs/release/loom-recording-script.md).
 *
 * Run from apps/frontend:
 *   npx tsx ../../tools/recording/record-walkthrough.ts
 *
 * Output:
 *   tools/recording/output/walkthrough.webm
 */

import { chromium, type Page } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE = "http://localhost:3000";

// Seeded IDs (pulled from local postgres at recording time — see docs/release/loom-recording-script.md):
const FASTAPI_COURSE_SLUG = "fastapi-from-zero";
const CONVERSATION_ID = "mTdcgt62BgYAdvnSJ5x94";
const MESSAGE_ID = "A5Xttfu96DQYYettFOj8H";
const DRAFT_COURSE_ID = "l4RLWhytCTkaBSWrD1SBC";

const OUT_DIR = path.resolve(__dirname, "output");
fs.mkdirSync(OUT_DIR, { recursive: true });

interface Beat {
  title: string;
  caption: string;
  duration: number; // milliseconds
  go: (page: Page) => Promise<void>;
}

const BEATS: Beat[] = [
  {
    title: "Lumen",
    caption:
      "Open-source agentic-AI learning platform. Running locally for this walkthrough; public demo at lumen.ahmedhobeishy.de.",
    duration: 12000,
    go: async (page) => {
      await page.goto(BASE);
      await page.waitForLoadState("domcontentloaded");
    },
  },
  {
    title: "Course-scoped RAG tutor",
    caption:
      "Every learner has a course-scoped tutor. Answers cite the specific lesson chunk they're grounded in.",
    duration: 15000,
    go: async (page) => {
      // Log in as student
      await page.goto(`${BASE}/login`);
      await page.getByLabel(/email/i).fill("student@lumen.test");
      await page.getByLabel(/password/i).fill("Learn!2026");
      await page.click('button[type="submit"]');
      await page.waitForURL(/dashboard|\/$/, { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(800);
      // Open the learn surface for the seeded FastAPI course
      await page.goto(`${BASE}/learn/${FASTAPI_COURSE_SLUG}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(1200);
      // Toggle the tutor sidebar open so the camera sees lesson + tutor together
      const askBtn = page.getByRole("button", { name: /ask the tutor/i }).first();
      if (await askBtn.count()) {
        await askBtn.click().catch(() => {});
        await page.waitForTimeout(800);
      }
    },
  },
  {
    title: "Multi-agent planner-orchestrator",
    caption:
      "Planner over 5 sub-agents: retriever, web-searcher, code-runner, quiz-gen, concept-explainer. The trace surface shows what fired.",
    duration: 15000,
    go: async (page) => {
      // Trace surface — top of the page shows the planner + tool calls (which
      // is exactly what this caption describes). Beat 4 scrolls down to the
      // retrieval audit so the visual changes even though it's the same page.
      await page.goto(`${BASE}/dashboard/tutor/${CONVERSATION_ID}/turn/${MESSAGE_ID}`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(500);
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior }));
    },
  },
  {
    title: "Observable agent traces",
    caption:
      "Every turn writes a first-class trace — tokens, USD cost, latency, planner tool-calls, retrieval audit. Built in, not bolted on.",
    duration: 15000,
    go: async (page) => {
      // Scroll down to the retrieval-audit / step breakdown so beat 4 reads
      // visually different from beat 3's framing of the same trace page.
      await page.evaluate(() => {
        // Try to scroll to a retrieval-audit landmark; fall back to a fixed offset.
        const target =
          document.querySelector('[data-testid="retrieval-audit"]') ||
          Array.from(document.querySelectorAll("h2,h3"))
            .find((el) => /retrieval|audit/i.test(el.textContent || "")) ||
          null;
        if (target) {
          (target as HTMLElement).scrollIntoView({ behavior: "instant" as ScrollBehavior, block: "start" });
        } else {
          window.scrollTo({ top: 600, behavior: "instant" as ScrollBehavior });
        }
      });
      await page.waitForTimeout(400);
    },
  },
  {
    title: "Self-critique authoring loop",
    caption:
      "Instructor side: researcher → outliner → critic → reviser → drafter → final-critic. Replay each step; drafts come out reviewer-ready.",
    duration: 15000,
    go: async (page) => {
      // Re-login as teacher
      await page.goto(`${BASE}/login`);
      await page.getByLabel(/email/i).fill("teacher@lumen.test");
      await page.getByLabel(/password/i).fill("Teach!2026");
      await page.click('button[type="submit"]');
      await page.waitForTimeout(1200);
      await page.goto(`${BASE}/studio/draft/${DRAFT_COURSE_ID}/replay`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(500);
    },
  },
  {
    title: "Production observability",
    caption:
      "Per-user cost meter, budget guards, eval suite (30 tutor + 10 authoring + 10 ingest items, LLM-as-judge). MCP server in the public registry.",
    duration: 15000,
    go: async (page) => {
      // Re-login as admin
      await page.goto(`${BASE}/login`);
      await page.getByLabel(/email/i).fill("admin@lumen.test");
      await page.getByLabel(/password/i).fill("Admin!2026");
      await page.click('button[type="submit"]');
      await page.waitForTimeout(1200);
      await page.goto(`${BASE}/admin/observability`);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(500);
    },
  },
];

async function injectCaption(page: Page, title: string, caption: string) {
  await page.evaluate(
    ({ title, caption }) => {
      const existing = document.getElementById("__lumen_caption");
      if (existing) existing.remove();
      const box = document.createElement("div");
      box.id = "__lumen_caption";
      box.style.cssText = `
        position: fixed; left: 32px; right: 32px; bottom: 32px;
        background: rgba(15,15,20,0.92); color: #fff;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
        padding: 18px 24px; border-radius: 12px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.4);
        z-index: 2147483647; pointer-events: none;
        border-left: 4px solid #C8FF00;
        animation: lumenSlide 0.4s ease-out;
      `;
      const titleEl = document.createElement("div");
      titleEl.textContent = title;
      titleEl.style.cssText =
        "font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #C8FF00;";
      const capEl = document.createElement("div");
      capEl.textContent = caption;
      capEl.style.cssText = "font-size: 16px; line-height: 1.5; color: #e8e8ea;";
      box.appendChild(titleEl);
      box.appendChild(capEl);
      const style = document.createElement("style");
      style.textContent =
        "@keyframes lumenSlide { from { transform: translateY(40px); opacity: 0 } to { transform: translateY(0); opacity: 1 } }";
      document.head.appendChild(style);
      document.body.appendChild(box);
    },
    { title, caption },
  );
}

async function clearCaption(page: Page) {
  await page.evaluate(() => {
    const el = document.getElementById("__lumen_caption");
    if (el) el.remove();
  });
}

async function main() {
  console.log("Launching browser...");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: OUT_DIR, size: { width: 1440, height: 900 } },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  // Run each beat
  for (let i = 0; i < BEATS.length; i++) {
    const beat = BEATS[i];
    console.log(`Beat ${i + 1}: ${beat.title}`);
    try {
      await beat.go(page);
    } catch (e) {
      console.error(`Beat ${i + 1} navigation failed:`, e);
    }
    await injectCaption(page, beat.title, beat.caption);
    await page.waitForTimeout(beat.duration);
    await clearCaption(page);
    await page.waitForTimeout(400);
  }

  console.log("Closing context (finalizes video)...");
  await context.close();
  await browser.close();

  // Rename the video to a stable filename
  const files = fs.readdirSync(OUT_DIR).filter((f) => f.endsWith(".webm"));
  if (files.length > 0) {
    const sorted = files.sort(
      (a, b) =>
        fs.statSync(path.join(OUT_DIR, b)).mtimeMs -
        fs.statSync(path.join(OUT_DIR, a)).mtimeMs,
    );
    const final = path.join(OUT_DIR, "walkthrough.webm");
    if (sorted[0] !== "walkthrough.webm") {
      fs.renameSync(path.join(OUT_DIR, sorted[0]), final);
    }
    console.log(`Video saved: ${final}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
