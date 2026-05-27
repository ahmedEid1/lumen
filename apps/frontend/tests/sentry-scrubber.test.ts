import { describe, expect, it } from "vitest";

import { beforeSendScrub } from "@/lib/sentry/scrubber";

const SCRUBBED = "<scrubbed by lumen.sentry_scrubber>";

describe("beforeSendScrub", () => {
  it("scrubs tutor-category breadcrumbs to constant marker", () => {
    const event = {
      breadcrumbs: [
        { category: "tutor", message: "Sent: explain closures", data: { q: "x" } },
        { category: "navigation", message: "to /home" },
      ],
    };
    const out = beforeSendScrub(event);
    expect(out.breadcrumbs?.[0].message).toBe(SCRUBBED);
    expect(out.breadcrumbs?.[0].data).toBeUndefined();
    expect(out.breadcrumbs?.[1].message).toBe("to /home");
  });

  it("scrubs request data when URL matches /api/v1/tutor/*", () => {
    const event = {
      request: {
        url: "https://lumen.example/api/v1/tutor/turns",
        data: { content: "secret question" },
      },
    };
    const out = beforeSendScrub(event);
    expect(out.request?.data).toBe(SCRUBBED);
  });

  it("leaves request data alone on non-tutor URLs", () => {
    const event = {
      request: {
        url: "https://lumen.example/api/v1/courses",
        data: { slug: "ts-variance" },
      },
    };
    const out = beforeSendScrub(event);
    expect(out.request?.data).toEqual({ slug: "ts-variance" });
  });

  it("scrubs high-risk vars in stacktrace frames", () => {
    const event = {
      exception: {
        values: [
          {
            value: "boom",
            stacktrace: {
              frames: [
                {
                  vars: {
                    prompt: "SECRET PROMPT",
                    innocuous: "kept",
                    user_message: "explain X",
                  },
                },
              ],
            },
          },
        ],
      },
    };
    const out = beforeSendScrub(event);
    const vars = out.exception!.values![0].stacktrace!.frames![0].vars!;
    expect(vars.prompt).toBe(SCRUBBED);
    expect(vars.user_message).toBe(SCRUBBED);
    expect(vars.innocuous).toBe("kept");
  });

  it("scrubs exception message containing high-risk substring", () => {
    const event = {
      exception: {
        values: [{ value: "Failed to render tutor reply: 'secret'", stacktrace: { frames: [] } }],
      },
    };
    const out = beforeSendScrub(event);
    expect(out.exception!.values![0].value).toBe(SCRUBBED);
  });

  it("scrubs top-level event message", () => {
    const event = { message: "tutor stream timed out at index 3" };
    const out = beforeSendScrub(event);
    expect(out.message).toBe(SCRUBBED);
  });

  // L39 rescue (Codex P1×2 + P2)

  it("scrubs request URL + query_string on tutor paths (P2)", () => {
    const event = {
      request: {
        url: "https://lumen.example/api/v1/tutor/turns?q=secret",
        query_string: "q=secret",
        data: { content: "secret" },
      },
    };
    const out = beforeSendScrub(event);
    expect(out.request?.url).toBe(SCRUBBED);
    expect(out.request?.query_string).toBe(SCRUBBED);
    expect(out.request?.data).toBe(SCRUBBED);
  });

  it("scrubs fetch breadcrumb data when URL is tutor-namespace (P1)", () => {
    const event = {
      breadcrumbs: [
        {
          category: "fetch",
          message: "POST 201",
          data: {
            url: "https://lumen.example/api/v1/tutor/turns",
            payload: "secret prompt",
            body: '{"content":"secret"}',
          },
        },
        {
          category: "navigation",
          message: "to /home",
          data: { from: "/learn", to: "/home" },
        },
      ],
    };
    const out = beforeSendScrub(event);
    expect(out.breadcrumbs?.[0].data?.payload).toBe(SCRUBBED);
    expect(out.breadcrumbs?.[0].data?.body).toBe(SCRUBBED);
    expect(out.breadcrumbs?.[0].data?.url).toBe(SCRUBBED);
    // Non-tutor navigation breadcrumb is untouched.
    expect(out.breadcrumbs?.[1].data?.from).toBe("/learn");
  });

  it("scrubs Sentry extra dict for high-risk keys (P1)", () => {
    const event = {
      extra: {
        prompt: "SECRET PROMPT",
        user_message: "explain X",
        innocuous: "kept",
      },
    };
    const out = beforeSendScrub(event);
    expect(out.extra?.prompt).toBe(SCRUBBED);
    expect(out.extra?.user_message).toBe(SCRUBBED);
    expect(out.extra?.innocuous).toBe("kept");
  });

  it("scrubs Sentry contexts dicts recursively (P1)", () => {
    const event = {
      contexts: {
        tutor: {
          prompt: "SECRET",
          turn_id: "kept",
        },
        device: {
          screen_width: 1920,
        },
      },
    };
    const out = beforeSendScrub(event);
    expect(out.contexts?.tutor?.prompt).toBe(SCRUBBED);
    expect(out.contexts?.tutor?.turn_id).toBe("kept");
    expect(out.contexts?.device?.screen_width).toBe(1920);
  });

  it("scrubs extra string values containing high-risk substrings (P1)", () => {
    const event = {
      extra: {
        diagnostic: "stream timeout while in synth_chunk loop",
        timestamp: "2026-05-27T12:00:00Z",
      },
    };
    const out = beforeSendScrub(event);
    expect(out.extra?.diagnostic).toBe(SCRUBBED);
    expect(out.extra?.timestamp).toBe("2026-05-27T12:00:00Z");
  });
});
