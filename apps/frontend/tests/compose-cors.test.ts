import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression guard: the e2e container's browser loads the
// dev bundle from `http://web:3000`, so api requests originate
// from that origin. If `CORS_ORIGINS` in the api environment
// doesn't include `http://web:3000`, the api returns
// `400 Disallowed CORS origin` for the preflight and every
// e2e auth/login call fails silently. Pin the docker-compose
// default so a future edit that drops it fails CI before the
// symptom resurfaces.

function findComposeFile(): string | null {
  let dir = __dirname;
  for (let i = 0; i < 6; i++) {
    const candidate = join(dir, "docker-compose.yml");
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  if (existsSync("/repo/docker-compose.yml")) return "/repo/docker-compose.yml";
  return null;
}

describe("docker-compose CORS_ORIGINS default", () => {
  const composePath = findComposeFile();

  it("docker-compose.yml is reachable from this test", () => {
    expect(composePath).toBeTruthy();
  });

  it("default CORS_ORIGINS includes both localhost:3000 and web:3000", () => {
    if (!composePath) return;
    const compose = readFileSync(composePath, "utf8");
    // Match the substitution default: ${CORS_ORIGINS:-[...]}
    const match = compose.match(
      /CORS_ORIGINS:\s*\$\{CORS_ORIGINS:-(\[[^\]]+\])\}/,
    );
    expect(match, "CORS_ORIGINS default not found in docker-compose.yml").toBeTruthy();
    const defaultValue = match![1];
    expect(defaultValue).toContain("http://localhost:3000");
    expect(defaultValue).toContain("http://web:3000");
  });
});
