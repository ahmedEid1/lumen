import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression guard for the iter-4 auto-deploy chain.
//
// Auto-deploy on push to main is implemented as:
//
//   ci.yml :: deploy
//     needs: [backend, frontend, build-images, e2e, accessibility]
//     if:   push to refs/heads/main
//     uses: ./.github/workflows/deploy.yml
//                  └─▶ deploy.yml :: deploy
//                       environment:
//                         name: production
//
// The two pieces of the design that are easy to silently break in a
// "while I'm here" edit are:
//
//   1. The `needs:` list on ci.yml's `deploy` job. Dropping `e2e` or
//      `accessibility` from it would let a deploy fire while those
//      gates are still red — exactly the "all gates green before
//      shipping" invariant we're trying to enforce.
//   2. The `environment: production` block on deploy.yml's `deploy`
//      job. Without it, the GitHub approval gate disappears and
//      deploys fly through unattended.
//
// This test reads both YAML files (via a read-only mount; see the
// `web` service in docker-compose.yml) and asserts both shapes.

function findRepoRoot(): string | null {
  // The compose mount lands the repo at /repo, but in non-container
  // environments we walk up from __dirname looking for a Makefile.
  if (existsSync("/repo/Makefile")) return "/repo";
  let dir = __dirname;
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(dir, "Makefile"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function readWorkflow(repoRoot: string, name: string): string {
  return readFileSync(join(repoRoot, ".github", "workflows", name), "utf8");
}

// Extract the body of a named top-level job from a workflow file.
// "body" here means every line from `<name>:` up to (but not
// including) the next sibling job header. We rely on the workflow
// being indented at 2 spaces under `jobs:`, which is the convention
// across this repo's workflows.
function extractJobBody(workflow: string, jobName: string): string | null {
  const lines = workflow.split("\n");
  let inJobsBlock = false;
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^jobs:\s*$/.test(line)) {
      inJobsBlock = true;
      continue;
    }
    if (!inJobsBlock) continue;
    // A top-level job header is exactly 2 spaces of indent followed
    // by `<name>:` and end-of-line.
    if (new RegExp(`^  ${jobName}:\\s*$`).test(line)) {
      start = i;
      continue;
    }
    if (start !== -1 && /^  [a-zA-Z_-]+:\s*$/.test(line)) {
      // Hit the next sibling job — return the body.
      return lines.slice(start, i).join("\n");
    }
  }
  if (start === -1) return null;
  return lines.slice(start).join("\n");
}

describe("ci.yml auto-deploy chain shape (iter 4)", () => {
  const repoRoot = findRepoRoot();

  it("repo root is reachable from this test", () => {
    expect(repoRoot).toBeTruthy();
  });

  it("ci.yml :: deploy fans in every ship-readiness gate", () => {
    if (!repoRoot) return;
    const ci = readWorkflow(repoRoot, "ci.yml");
    const body = extractJobBody(ci, "deploy");
    expect(body, "no `deploy:` job found in ci.yml").toBeTruthy();

    // Pull the flow-style needs list. Block-style would also be valid
    // YAML but the convention in this repo is flow style, and pinning
    // the convention is part of the regression — a switch to block
    // style would still merit a re-review of this test.
    const m = body!.match(/^\s*needs:\s*\[([^\]]+)\]/m);
    expect(m, "no `needs: [...]` on ci.yml :: deploy").toBeTruthy();
    const items = m![1]
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    for (const required of [
      "backend",
      "frontend",
      "build-images",
      "e2e",
      "accessibility",
    ]) {
      expect(
        items,
        `ci.yml :: deploy.needs is missing '${required}' — adding a new gate above means appending its job name here so the deploy waits for it.`,
      ).toContain(required);
    }
  });

  it("ci.yml :: deploy is push-to-main only", () => {
    if (!repoRoot) return;
    const ci = readWorkflow(repoRoot, "ci.yml");
    const body = extractJobBody(ci, "deploy");
    expect(body).toBeTruthy();

    const ifLine = body!.match(/^\s*if:\s*(.+)$/m);
    expect(ifLine, "no `if:` on ci.yml :: deploy").toBeTruthy();
    expect(ifLine![1]).toContain("github.event_name == 'push'");
    expect(ifLine![1]).toContain("github.ref == 'refs/heads/main'");
  });

  it("ci.yml :: deploy invokes deploy.yml as a reusable workflow", () => {
    if (!repoRoot) return;
    const ci = readWorkflow(repoRoot, "ci.yml");
    const body = extractJobBody(ci, "deploy");
    expect(body).toBeTruthy();
    expect(body!).toMatch(/^\s*uses:\s*\.\/\.github\/workflows\/deploy\.yml\s*$/m);
  });

  it("deploy.yml :: deploy declares the `production` environment", () => {
    if (!repoRoot) return;
    const deployYml = readWorkflow(repoRoot, "deploy.yml");
    const body = extractJobBody(deployYml, "deploy");
    expect(body, "no `deploy:` job found in deploy.yml").toBeTruthy();

    // Both forms are valid YAML:
    //   environment: production              (string)
    //   environment:                          (block)
    //     name: production
    // We accept either — what we forbid is the absence of any
    // `environment:` key on this job. As of 4c6ef4d the env carries no
    // required-reviewer gate (deploys auto-proceed; see ADR notes in
    // docs/ci-cd.md), but the block must stay: it scopes deployment
    // history + the `main`-only branch policy + any env-scoped secrets,
    // and it's the seam where a reviewer gate would be re-added.
    const block = body!.match(/^\s*environment:\s*$/m);
    const inline = body!.match(/^\s*environment:\s*production\s*$/m);
    const hasEnvironment =
      Boolean(inline) ||
      (Boolean(block) && /^\s+name:\s*production\s*$/m.test(body!));
    expect(
      hasEnvironment,
      "deploy.yml :: deploy is missing `environment: production` — that drops the deploy-history grouping, branch policy, and env-secret scope (and the seam for re-adding a reviewer gate).",
    ).toBe(true);
  });
});
