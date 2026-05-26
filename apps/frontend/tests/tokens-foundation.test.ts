import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Regression guard for the loop-1 token foundation.
//
// AUDIT.md §2 / loop-1-spec.md establish a token scale that the next 19
// loops will reference. The values themselves are free to evolve, but the
// *names* are load-bearing — any primitive that ships `<EmptyState
// padding="md">` or `<Dialog z="modal">` depends on these tokens being
// present in globals.css with the documented Tailwind aliases.
//
// This test reads source files directly relative to __dirname (the
// `apps/frontend/tests/` directory) — vitest runs inside the `web`
// container with `./apps/frontend:/app`, so the frontend workspace is
// available the entire time the suite runs. No /repo mount needed.
//
// Values are intentionally NOT asserted (only token presence) — a future
// loop should be free to swap the `--info` hue or re-tune the spring
// curve without this test going red. Token *removal* is what we guard.

const FRONTEND_ROOT = resolve(__dirname, "..");

function readSrc(rel: string): string {
  return readFileSync(resolve(FRONTEND_ROOT, rel), "utf8");
}

// Extract the body of a CSS block whose selector matches `selector` —
// e.g. `:root` inside `@layer base`, `.light`, or `@theme inline`. Body
// is the text between the `{` and the matching `}`, depth-tracked.
function extractBlock(css: string, selectorRe: RegExp): string | null {
  const m = css.match(selectorRe);
  if (!m) return null;
  const start = (m.index ?? 0) + m[0].length;
  let depth = 1;
  for (let i = start; i < css.length; i++) {
    const ch = css[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return css.slice(start, i);
    }
  }
  return null;
}

describe("loop-1 token foundation", () => {
  describe(":root block tokens (theme-neutral + dark-default colour overrides)", () => {
    it("declares the new --info colour pair", () => {
      const css = readSrc("src/styles/globals.css");
      const rootBody = extractBlock(css, /:root\s*\{/);
      expect(rootBody, "no :root block found in globals.css").toBeTruthy();
      expect(rootBody!).toMatch(/--info:\s/);
      expect(rootBody!).toMatch(/--info-foreground:\s/);
    });

    it("declares the named --space-* scale", () => {
      const css = readSrc("src/styles/globals.css");
      const rootBody = extractBlock(css, /:root\s*\{/);
      for (const name of [
        "--space-xs",
        "--space-sm",
        "--space-md",
        "--space-lg",
        "--space-xl",
        "--space-2xl",
        "--space-3xl",
      ]) {
        expect(rootBody!, `:root missing ${name}`).toMatch(
          new RegExp(`${name}:\\s`),
        );
      }
    });

    it("declares the --z-* semantic ramp", () => {
      const css = readSrc("src/styles/globals.css");
      const rootBody = extractBlock(css, /:root\s*\{/);
      for (const name of [
        "--z-base",
        "--z-sticky",
        "--z-overlay",
        "--z-modal",
        "--z-popover",
        "--z-toast",
        "--z-tooltip",
      ]) {
        expect(rootBody!, `:root missing ${name}`).toMatch(
          new RegExp(`${name}:\\s`),
        );
      }
    });

    it("declares the --opacity-* semantic ramp", () => {
      const css = readSrc("src/styles/globals.css");
      const rootBody = extractBlock(css, /:root\s*\{/);
      for (const name of [
        "--opacity-disabled",
        "--opacity-hover",
        "--opacity-overlay",
        "--opacity-decoration",
      ]) {
        expect(rootBody!, `:root missing ${name}`).toMatch(
          new RegExp(`${name}:\\s`),
        );
      }
    });

    it("declares the spring easings + motion constants", () => {
      const css = readSrc("src/styles/globals.css");
      const rootBody = extractBlock(css, /:root\s*\{/);
      for (const name of [
        "--ease-spring-soft",
        "--ease-spring-firm",
        "--motion-rise-distance",
        "--motion-press-scale",
      ]) {
        expect(rootBody!, `:root missing ${name}`).toMatch(
          new RegExp(`${name}:\\s`),
        );
      }
    });
  });

  describe(".light theme overrides", () => {
    it("declares a light-mode --info override (deeper blue for AA on light surfaces)", () => {
      const css = readSrc("src/styles/globals.css");
      const lightBody = extractBlock(css, /\.light\s*\{/);
      expect(lightBody, "no .light block found in globals.css").toBeTruthy();
      expect(lightBody!).toMatch(/--info:\s/);
      expect(lightBody!).toMatch(/--info-foreground:\s/);
    });
  });

  describe("@theme inline Tailwind utility aliases", () => {
    it("aliases the info colour for `bg-info` / `text-info-foreground`", () => {
      const css = readSrc("src/styles/globals.css");
      const themeBody = extractBlock(css, /@theme\s+inline\s*\{/);
      expect(themeBody, "no @theme inline block found").toBeTruthy();
      expect(themeBody!).toMatch(/--color-info:\s/);
      expect(themeBody!).toMatch(/--color-info-foreground:\s/);
    });

    // The `--spacing-*` aliases in @theme inline were REMOVED in the
    // loop-7-followup hotfix — Tailwind 4 reads the `--spacing-*`
    // namespace for max-width utilities too, so `--spacing-3xl: 6rem`
    // overrode `max-w-3xl` from 48rem default to 96px. The named
    // scale lives in :root as `--space-*` and is consumed via
    // arbitrary Tailwind values (`p-[var(--space-md)]`). This test
    // now asserts the OPPOSITE: that the @theme block does NOT
    // contain `--spacing-*` aliases that would re-introduce the
    // regression.
    it("does NOT alias the spacing scale in @theme (avoids max-w-* collision)", () => {
      const css = readSrc("src/styles/globals.css");
      const themeBody = extractBlock(css, /@theme\s+inline\s*\{/);
      for (const name of [
        "--spacing-xs",
        "--spacing-sm",
        "--spacing-md",
        "--spacing-lg",
        "--spacing-xl",
        "--spacing-2xl",
        "--spacing-3xl",
      ]) {
        // Match real CSS declarations only: start-of-line indent
        // followed by the token name. Excludes the comment prose in
        // globals.css that names the token as an example.
        expect(
          themeBody!,
          `@theme should NOT contain ${name} as a real declaration — it collides with Tailwind 4's max-w-* utility derivation. See the @theme block's comment in globals.css.`,
        ).not.toMatch(new RegExp(`^\\s+${name}:\\s`, "m"));
      }
    });

    it("aliases the z-index ramp for `z-sticky` / `z-modal` etc.", () => {
      const css = readSrc("src/styles/globals.css");
      const themeBody = extractBlock(css, /@theme\s+inline\s*\{/);
      for (const name of [
        "--z-index-sticky",
        "--z-index-overlay",
        "--z-index-modal",
        "--z-index-popover",
        "--z-index-toast",
        "--z-index-tooltip",
      ]) {
        expect(themeBody!, `@theme missing ${name}`).toMatch(
          new RegExp(`${name}:\\s`),
        );
      }
    });

    it("aliases the opacity ramp for `opacity-disabled` / `opacity-hover` etc.", () => {
      const css = readSrc("src/styles/globals.css");
      const themeBody = extractBlock(css, /@theme\s+inline\s*\{/);
      for (const name of [
        "--opacity-disabled",
        "--opacity-hover",
        "--opacity-overlay",
        "--opacity-decoration",
      ]) {
        expect(themeBody!, `@theme missing ${name}`).toMatch(
          new RegExp(`${name}:\\s`),
        );
      }
    });
  });

  describe("primitive duration-literal sweep", () => {
    const sweepTargets = [
      "src/components/ui/button.tsx",
      "src/components/ui/input.tsx",
      "src/components/ui/textarea.tsx",
    ];

    for (const target of sweepTargets) {
      it(`${target} uses duration-base, not the duration-[160ms] literal`, () => {
        const src = readSrc(target);
        expect(
          src,
          `${target} still contains the duration-[160ms] literal — the loop-1 sweep should have replaced it with duration-base`,
        ).not.toMatch(/duration-\[160ms\]/);
        expect(src).toMatch(/duration-base/);
      });
    }

    it("progress.tsx references --duration-slow + --ease-out-quart, not the 240ms cubic-bezier literal", () => {
      const src = readSrc("src/components/ui/progress.tsx");
      expect(
        src,
        "progress.tsx still contains the cubic-bezier(0.16, 1, 0.3, 1) literal — loop-1 should replace it with var(--ease-out-quart)",
      ).not.toMatch(/cubic-bezier\(0\.16,\s*1,\s*0\.3,\s*1\)/);
      expect(src).toMatch(/var\(--duration-slow\)/);
      expect(src).toMatch(/var\(--ease-out-quart\)/);
    });
  });
});
