/**
 * S2.11/S2.12 — the two-control lifecycle + share endpoint client.
 *
 * Pins that the Studio's publish/share controls hit the explicit lifecycle
 * endpoints (POST /publish|/unpublish|/share|/unshare|/resubmit), NOT the old
 * PATCH-as-publish path. Mocks ``global.fetch`` and asserts the method + URL
 * for each call so the contract the UI depends on stays stable (DR-5: types.ts
 * + this client are hand-written, never regenerated).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Courses } from "@/lib/api/endpoints";

type FetchArgs = [RequestInfo | URL, RequestInit | undefined];

function mockFetch() {
  const spy = vi.fn(
    async () =>
      new Response(JSON.stringify({ id: "c1", status: "published" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  // @ts-expect-error - assigning the test double
  global.fetch = spy;
  return spy;
}

describe("Courses lifecycle + share endpoints", () => {
  let originalFetch: typeof globalThis.fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const cases: [keyof typeof Courses, string][] = [
    ["publish", "/api/v1/courses/c1/publish"],
    ["unpublish", "/api/v1/courses/c1/unpublish"],
    ["share", "/api/v1/courses/c1/share"],
    ["unshare", "/api/v1/courses/c1/unshare"],
    ["resubmit", "/api/v1/courses/c1/resubmit"],
  ];

  for (const [method, path] of cases) {
    it(`Courses.${method} POSTs to ${path}`, async () => {
      const spy = mockFetch();
      // @ts-expect-error - dynamic method access for the table-driven test
      await Courses[method]("c1");
      const [url, init] = spy.mock.calls[0] as FetchArgs;
      expect(String(url)).toContain(path);
      expect(init?.method).toBe("POST");
    });
  }

  it("moderationQueue GETs the admin queue", async () => {
    const spy = vi.fn(
      async () =>
        new Response("[]", { status: 200, headers: { "content-type": "application/json" } }),
    );
    // @ts-expect-error - test double
    global.fetch = spy;
    await Courses.moderationQueue();
    const [url, init] = spy.mock.calls[0] as FetchArgs;
    expect(String(url)).toContain("/api/v1/admin/courses/moderation-queue");
    // GET (no explicit method on the api() default)
    expect(init?.method ?? "GET").toBe("GET");
  });
});
