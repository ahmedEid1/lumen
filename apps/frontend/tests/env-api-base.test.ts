import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Iter 102 + 105: browser-side fetches go through Next.js's
// /api/v1/* rewrite (added in iter 105's next.config.ts) so the
// call is same-origin from the browser. That dodges CORS AND the
// SameSite=Strict cookie trap that iter 102's direct-to-api fix
// alone couldn't solve. The browser-side base must therefore be
// a relative URL ("") so client.ts emits paths like
// `/api/v1/auth/login` that hit the current origin.
//
// This test pins both branches (browser → "", SSR → internal
// URL) so a revert that re-introduces a cross-origin base fails
// CI before silent login failures resurface in the e2e run.

describe("env.API_BASE_URL routes via same-origin rewrite", () => {
  const ORIGINAL_LOCATION = globalThis.window?.location;

  function setLocation(hostname: string) {
    Object.defineProperty(globalThis.window, "location", {
      value: { ...ORIGINAL_LOCATION, hostname },
      writable: true,
    });
  }

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    Object.defineProperty(globalThis.window, "location", {
      value: ORIGINAL_LOCATION,
      writable: true,
    });
  });

  it("returns an empty string in the browser (same-origin relative URLs)", async () => {
    setLocation("web");
    const { env } = await import("../src/lib/env");
    expect(env.API_BASE_URL).toBe("");
  });

  it("returns an empty string from any browser host (host browsing too)", async () => {
    setLocation("localhost");
    const { env } = await import("../src/lib/env");
    expect(env.API_BASE_URL).toBe("");
  });

  it("returns an empty string from a prod-like host", async () => {
    setLocation("lumen.example.com");
    const { env } = await import("../src/lib/env");
    expect(env.API_BASE_URL).toBe("");
  });

  it("API_INTERNAL_BASE_URL keeps its docker-network value for SSR", async () => {
    const { env } = await import("../src/lib/env");
    expect(env.API_INTERNAL_BASE_URL).toMatch(/^https?:\/\//);
    expect(env.API_INTERNAL_BASE_URL).not.toBe("");
  });
});
