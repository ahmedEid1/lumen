/**
 * L50 + L51 — robots.txt renders at runtime, and the empty blog stays
 * out of search results.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import robots, { revalidate as robotsRevalidate } from "@/app/robots";
import sitemap from "@/app/sitemap";
import { metadata as blogMetadata } from "@/app/blog/page";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("robots.txt", () => {
  it("revalidates at runtime instead of freezing the build-time host", () => {
    // Without a revalidate (or dynamic) export Next prerenders robots.txt
    // during `pnpm build`, where NEXT_PUBLIC_API_BASE_URL is unset.
    expect(robotsRevalidate).toBe(3600);
  });

  it("points crawlers at the sitemap on the same host", () => {
    const r = robots();
    expect(r.sitemap).toBe(`${r.host}/sitemap.xml`);
  });
});

describe("blog while it has no posts", () => {
  it("is left out of the sitemap", async () => {
    // Catalog fetch fails → the sitemap falls back to static routes only.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const urls = (await sitemap()).map((e) => e.url);
    expect(urls.some((u) => u.endsWith("/eval"))).toBe(true);
    expect(urls.some((u) => u.endsWith("/blog"))).toBe(false);
  });

  it("is marked noindex", () => {
    expect(blogMetadata.robots).toMatchObject({ index: false });
  });
});
