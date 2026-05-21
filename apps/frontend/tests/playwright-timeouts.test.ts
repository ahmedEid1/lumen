import { describe, expect, it } from "vitest";
import playwrightConfig from "../playwright.config";

// Regression guard: Next.js dev mode compiles each route on the
// first hit on a single thread. With Playwright's default 6
// parallel workers, six cold compiles serialise behind one mutex
// and the slow ones blew past 60s — every spec failed
// `page.goto: Test timeout of 60000ms exceeded`. The two pins here:
//
//   1. timeouts roomy enough for one cold compile (>=60s)
//   2. workers capped low enough that compiles don't queue
//      indefinitely (<=2 when nothing overrides it)
//
// If you switch the e2e service from `pnpm dev` to a pre-built
// `pnpm start` against `next build` output, the worker cap is no
// longer needed — set `PLAYWRIGHT_WORKERS=6` (or undefined) and
// delete the worker-count assertion below.

describe("Playwright timeouts", () => {
  it("per-test timeout >= 60s (dev-compile headroom)", () => {
    expect(playwrightConfig.timeout ?? 0).toBeGreaterThanOrEqual(60_000);
  });

  it("navigationTimeout >= 60s", () => {
    const nav = playwrightConfig.use?.navigationTimeout ?? 0;
    expect(nav).toBeGreaterThanOrEqual(60_000);
  });

  it("actionTimeout >= 10s", () => {
    const action = playwrightConfig.use?.actionTimeout ?? 0;
    expect(action).toBeGreaterThanOrEqual(10_000);
  });

  it("default workers <= 2 to avoid Next dev compile contention", () => {
    // Without PLAYWRIGHT_WORKERS in env this is the value we ship.
    const workers = playwrightConfig.workers;
    expect(typeof workers === "number" ? workers : 999).toBeLessThanOrEqual(2);
  });
});
