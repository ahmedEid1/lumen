import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Regression guard: the `web` dev image is alpine (musl), so
// Playwright's browser binaries — which only ship for glibc —
// don't run inside it. The fix is a dedicated `e2e` service
// built from `apps/frontend/Dockerfile.e2e`, which extends
// `mcr.microsoft.com/playwright:vX.Y.Z-jammy` (chromium /
// firefox / webkit pre-installed). That image MUST stay pinned
// to the same X.Y.Z as @playwright/test in package.json, AND
// @playwright/test MUST be pinned to an exact version — without
// a pnpm-lock.yaml a `^1.49.1` will silently resolve to a
// newer minor that the image's browser bundle can't satisfy.
//
// Path resolution: when run on a host (e.g. GH Actions), walk
// up from __dirname to find docker-compose.yml at the repo
// root. When run inside the `web` dev container, fall back to
// /repo/docker-compose.yml — bind-mounted read-only by
// docker-compose.yml for this purpose.

function findComposeFile(): string | null {
  let dir = __dirname;
  for (let i = 0; i < 6; i++) {
    const candidate = join(dir, "docker-compose.yml");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  const containerMount = resolve("/repo/docker-compose.yml");
  if (existsSync(containerMount)) return containerMount;
  return null;
}

describe("Playwright image pin", () => {
  const composePath = findComposeFile();
  const pkgPath = join(__dirname, "..", "package.json");
  const dockerfilePath = join(__dirname, "..", "Dockerfile.e2e");

  it("docker-compose.yml is reachable from this test", () => {
    expect(
      composePath,
      "could not find docker-compose.yml — when running inside the `web` container ensure the bind-mount at /repo/docker-compose.yml is present",
    ).toBeTruthy();
  });

  it("has an `e2e` service in docker-compose.yml", () => {
    if (!composePath) return;
    const compose = readFileSync(composePath, "utf8");
    expect(compose).toMatch(/^\s{2}e2e:\s*$/m);
  });

  it("@playwright/test is pinned to an exact version", () => {
    const pkg = JSON.parse(readFileSync(pkgPath, "utf8")) as {
      devDependencies: Record<string, string>;
    };
    const pwSpec = pkg.devDependencies["@playwright/test"];
    expect(
      pwSpec,
      "@playwright/test missing from devDependencies",
    ).toBeTruthy();

    // Without a pnpm-lock.yaml, the `^1.49.1`
    // resolved to 1.60.0 on a fresh install while the docker
    // image stayed pinned to v1.49.1 — playwright then couldn't
    // find its browsers. Until we commit a lockfile, the only
    // way to keep the runtime and image in lockstep is an
    // exact version spec.
    expect(
      pwSpec,
      "@playwright/test must be pinned to an exact version (no `^` / `~` / range) until a pnpm-lock.yaml is committed — otherwise the resolved runtime drifts above the docker image's browser bundle",
    ).toMatch(/^[0-9]+\.[0-9]+\.[0-9]+$/);
  });

  it("Dockerfile.e2e image tag matches the @playwright/test version", () => {
    const pkg = JSON.parse(readFileSync(pkgPath, "utf8")) as {
      devDependencies: Record<string, string>;
    };
    const pwVersion = pkg.devDependencies["@playwright/test"];

    const dockerfile = readFileSync(dockerfilePath, "utf8");
    // Match: FROM mcr.microsoft.com/playwright:v1.49.1-jammy
    const match = dockerfile.match(
      /FROM\s+mcr\.microsoft\.com\/playwright:v([0-9]+\.[0-9]+\.[0-9]+)-/,
    );
    expect(
      match,
      "no pinned Microsoft Playwright image FROM in apps/frontend/Dockerfile.e2e",
    ).toBeTruthy();
    expect(match![1]).toBe(pwVersion);
  });
});
