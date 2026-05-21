import { describe, expect, it } from "vitest";
import nextConfig from "../next.config";

// Regression guard: the e2e + cookies story relies on
// next.config.ts's `rewrites()` proxying /api/v1/* through to the
// internal api host. Drop that and same-origin requests fall
// back to cross-origin direct fetches — CORS preflight succeeds,
// but the auth cookies (SameSite=Strict) don't follow, so any
// post-login mutation silently fails.
//
// This test reads the resolved rewrites config and asserts that
// /api/v1/* still routes to the internal api host.

describe("next.config rewrites", () => {
  it("proxies /api/v1/:path* to the internal api host", async () => {
    expect(typeof nextConfig.rewrites).toBe("function");
    const rewrites = await nextConfig.rewrites!();
    const list = Array.isArray(rewrites) ? rewrites : rewrites.beforeFiles ?? [];
    const apiV1 = list.find((r) => r.source === "/api/v1/:path*");
    expect(apiV1, "no rewrite for /api/v1/:path* in next.config.ts").toBeTruthy();
    // Default destination uses the internal docker-network host.
    expect(apiV1!.destination).toMatch(/\/api\/v1\/:path\*$/);
    expect(apiV1!.destination).toMatch(/^https?:\/\/[^/]+/);
  });
});
