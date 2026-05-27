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
});
