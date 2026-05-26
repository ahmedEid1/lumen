import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  // Next.js dev mode compiles routes on first hit on a
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
    // 60s: hydration-gated auth forms (login/register/forgot/reset)
    // disable the submit button until React mounts; Next.js dev mode's
    // on-demand JIT compile + WebKit's slower hydration pipeline under
    // workers=2 parallel pressure has pushed the wait past 30s on cold
    // /login. 60s gives the worst observed combination headroom without
    // softening the signal on legitimate stalls (test-level timeout is
    // still 90s, so a stuck test still fails).
    actionTimeout: 60_000,
  },
  projects: [
    // Loop-6 "setup" project — logs in each seeded role once and
    // writes auth state to `.auth/*.json`. Downstream projects
    // depend on this so a per-role login() race never bites tests
    // that consume `storageState`. See `tests/e2e/auth.setup.ts`.
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
      dependencies: ["setup"],
    },
  ],
});
