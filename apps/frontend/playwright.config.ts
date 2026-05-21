import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  // Iter 100: Next.js dev mode compiles routes on first hit on a
  // single thread. With the default 6 parallel workers each cold-
  // loading a different page, compiles serialise behind one mutex
  // and the slow ones blew past 60s — every test failed
  // `page.goto: Test timeout of 60000ms exceeded`. Two coordinated
  // changes:
  //   1. lift per-test + navigation timeouts so a cold compile
  //      doesn't trip the test ceiling
  //   2. cap workers at 2 against `pnpm dev` so concurrent compiles
  //      don't trample each other (override locally with
  //      `PLAYWRIGHT_WORKERS=N` once we switch to a pre-built
  //      `pnpm start` target — compiled output has no per-hit
  //      cost and can re-parallelise).
  timeout: 90_000,
  workers: process.env.PLAYWRIGHT_WORKERS
    ? Number(process.env.PLAYWRIGHT_WORKERS)
    : 2,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    navigationTimeout: 60_000,
    actionTimeout: 15_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
