import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression guard: the Makefile's `test.web` target shells into the
// web container with a pnpm invocation that has to survive pnpm 9.15.0
// (the version pinned via `packageManager` in apps/frontend/package.json).
// pnpm 9 rejects `--run` as a top-level option, so `pnpm test --run`
// errors with `Unknown option: 'run'` before vitest ever starts. CI
// uses `pnpm exec vitest run` instead (see .github/workflows/ci.yml),
// and the Makefile must match — otherwise `make test.web` is broken
// for every contributor even though CI is green.

function findMakefile(): string | null {
  let dir = __dirname;
  for (let i = 0; i < 6; i++) {
    const candidate = join(dir, "Makefile");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  if (existsSync("/repo/Makefile")) return "/repo/Makefile";
  return null;
}

describe("Makefile test.web invocation", () => {
  const path = findMakefile();

  it("Makefile is reachable from this test", () => {
    expect(path).toBeTruthy();
  });

  it("test.web target uses `pnpm exec vitest run`, not `pnpm test --run`", () => {
    if (!path) return;
    const makefile = readFileSync(path, "utf8");
    // Extract the body of the test.web target (lines from
    // `test.web:` up to the next blank line or next target).
    const match = makefile.match(/^test\.web:[^\n]*\n((?:\t[^\n]*\n)+)/m);
    expect(match, "test.web target not found in Makefile").toBeTruthy();
    const body = match![1];
    // Recipe lines only — drop Makefile comment lines (whitespace
    // followed by `#`) so the explanatory comment that names the
    // broken form (`pnpm test --run`) doesn't trip the forbid-rule
    // below. We want the rule to bite only on real recipe lines.
    const recipeLines = body
      .split("\n")
      .filter((line) => !/^\t\s*#/.test(line))
      .join("\n");
    expect(recipeLines).toContain("pnpm exec vitest run");
    // The broken form must not reappear in an actual recipe line.
    // A bare `pnpm test` is fine (it just runs the package.json
    // script without extra args); what we forbid is the `--run`
    // flag that pnpm 9 rejects.
    expect(recipeLines).not.toMatch(/pnpm\s+test\s+--run/);
  });
});
