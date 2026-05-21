import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api/client";

type FetchArgs = [RequestInfo | URL, RequestInit | undefined];

function mockFetch(responder: (...args: FetchArgs) => Response | Promise<Response>) {
  const spy = vi.fn(responder as any);
  // @ts-expect-error - assigning the test double
  global.fetch = spy;
  return spy;
}

describe("api client", () => {
  let originalFetch: typeof globalThis.fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns the JSON body on success", async () => {
    mockFetch(
      async () =>
        new Response(JSON.stringify({ hello: "world" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const out = await api<{ hello: string }>("/api/v1/whatever");
    expect(out).toEqual({ hello: "world" });
  });

  it("serializes plain objects as JSON with the right header", async () => {
    const spy = mockFetch(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    await api("/api/v1/foo", { method: "POST", body: { a: 1 } });
    const [, init] = spy.mock.calls[0] as FetchArgs;
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe(JSON.stringify({ a: 1 }));
  });

  it("returns undefined on 204 without parsing", async () => {
    mockFetch(async () => new Response(null, { status: 204 }));
    const out = await api("/api/v1/empty");
    expect(out).toBeUndefined();
  });

  it("throws ApiError with code/message/details/requestId from the JSON envelope", async () => {
    mockFetch(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "course.not_found",
              message: "Course not found",
              details: { course_id: "abc" },
              request_id: "req_123",
            },
          }),
          { status: 404, headers: { "content-type": "application/json" } },
        ),
    );

    await expect(api("/api/v1/courses/abc")).rejects.toMatchObject({
      status: 404,
      code: "course.not_found",
      message: "Course not found",
      details: { course_id: "abc" },
      requestId: "req_123",
    });
    await expect(api("/api/v1/courses/abc")).rejects.toBeInstanceOf(ApiError);
  });

  it("falls back to status text when the body is plain text", async () => {
    mockFetch(async () => new Response("nope", { status: 500, statusText: "Server Error" }));
    await expect(api("/api/v1/x")).rejects.toMatchObject({
      status: 500,
      code: "http_error",
    });
  });

  it("attaches the bearer token when provided", async () => {
    const spy = mockFetch(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    await api("/api/v1/me", { token: "secret-token" });
    const headers = new Headers((spy.mock.calls[0] as FetchArgs)[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });
});
