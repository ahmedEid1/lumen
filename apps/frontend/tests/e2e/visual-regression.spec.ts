/**
 * Visual-regression baseline pass (loop 2 of the UI redesign).
 *
 * AUDIT.md §5 / loop-2-spec.md establish that without per-route
 * baselines the next 18 redesign loops are shipping blind — any
 * "while I'm here" tweak to a primitive could shift catalog cover
 * proportions or shrink a dashboard card and the CI signal would be
 * 0 until a human screenshot sweep. This spec writes the baselines.
 *
 * Coverage: 4 public routes × 2 themes = 8 baselines, chromium project
 * only (webkit's font / scrollbar variance doubts-doubles the
 * maintenance without proportional signal). Auth-gated routes
 * (/dashboard, /profile, /studio, /admin) are deferred to a later
 * loop — see the ROUTES comment below for the reason.
 *
 * Re-blessing baselines: when a loop intentionally changes a render,
 *   pnpm exec playwright test visual-regression.spec.ts \
 *     --project=chromium --update-snapshots
 * captures the new PNGs. The result doc for that loop must call out
 * which baselines were re-blessed.
 *
 * Test thresholds:
 *   maxDiffPixels: 100   — absorb anti-aliasing jitter; Playwright's
 *                          default (0) makes hosted-webfont cache
 *                          misses produce false reds.
 *   threshold:    0.2    — 20% colour delta before a pixel is "diff".
 *                          Recommended for prose-heavy screenshots.
 */
import { expect, test, type Page } from "@playwright/test";
import { login, preDismissOnboarding, type SeedRole } from "./helpers/login";

// Public-only routes for the loop-2 first baseline pass. Auth-gated
// routes (/dashboard, /profile, /studio, /admin) defer to a later
// loop — the login form's hydration gate races the dev-mode cold
// compile in the docker e2e environment, which causes some screenshots
// to land on the login page instead of the post-login target. Loop 3
// ships the `<AuthCard>` + `useHydrated()` primitives that will make
// the form's enabled-state predictable, and the auth-gated baselines
// land then (or once we wire the e2e suite to the docker-compose.ci.yml
// overlay's prod-build web service, whichever comes first).
const ROUTES = [
  { name: "home", path: "/", auth: null as SeedRole | null },
  { name: "catalog", path: "/courses", auth: null },
  { name: "login", path: "/login", auth: null },
  { name: "register", path: "/register", auth: null },
] as const;

const THEMES = ["dark", "light"] as const;

// The seeded data has to be in place. If a CI runner is on a stack
// that never `make seed`'d (e.g. a smoke env), this spec is the wrong
// thing to gate on; the env var lets the runner opt out. Default-on
// matches the existing e2e specs' assumption.
const SEED_AVAILABLE = process.env.SEED_AVAILABLE !== "false";

/**
 * Inject the theme into localStorage via `addInitScript` so it lands
 * before next-themes mounts on first paint. The ThemeProvider in
 * `apps/frontend/src/app/layout.tsx` uses `attribute="class"` +
 * default key `theme`, so setting the key + class together makes the
 * very first render correct (no flash of wrong theme between hydration
 * and the read).
 */
async function pinTheme(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.addInitScript((t) => {
    try {
      localStorage.setItem("theme", t);
      // Mirror next-themes' DOM application so the first paint after
      // hydration matches the localStorage value. ThemeProvider with
      // attribute="class" toggles the `dark` / `light` class on <html>;
      // when we land light, we also need to remove `dark` (which
      // ThemeProvider's default behaviour leaves on the SSR shell).
      const html = document.documentElement;
      if (t === "light") {
        html.classList.add("light");
        html.classList.remove("dark");
        html.style.colorScheme = "light";
      } else {
        html.classList.add("dark");
        html.classList.remove("light");
        html.style.colorScheme = "dark";
      }
    } catch {
      /* localStorage access can be blocked in some browser modes; the
         worst case is the screenshot lands on the default theme,
         which would surface as a diff on the next run. */
    }
  }, theme);
}

test.describe("visual-regression baselines (loop 2)", () => {
  test.skip(!SEED_AVAILABLE, "SEED_AVAILABLE=false — visual regression needs seeded data");

  for (const route of ROUTES) {
    for (const theme of THEMES) {
      test(`${route.name} (${theme})`, async ({ page, browserName }) => {
        test.skip(
          browserName !== "chromium",
          "visual-regression baselines are pinned to chromium — webkit ships behavioural specs only",
        );

        await page.emulateMedia({
          colorScheme: theme,
          reducedMotion: "reduce",
        });
        await pinTheme(page, theme);
        await preDismissOnboarding(page);

        if (route.auth) {
          await login(page, route.auth, { waitForDashboard: false });
        }

        await page.goto(route.path, { waitUntil: "networkidle" });

        // Settle window for any post-hydration layout shift (lazy
        // images on catalog, sticky header initial paint, badge fade).
        // Less than the 240ms slow-motion duration so we don't capture
        // mid-animation.
        await page.waitForTimeout(300);

        await expect(page).toHaveScreenshot(`${route.name}-${theme}.png`, {
          fullPage: true,
          maxDiffPixels: 100,
          threshold: 0.2,
          animations: "disabled",
        });
      });
    }
  }
});
