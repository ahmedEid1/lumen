import { describe, expect, it } from "vitest";
import { pickResumeLessonId } from "@/lib/lesson-resume";
import type { LessonOut } from "@/lib/api/types";

function L(id: string, completed = false): LessonOut {
  return {
    id,
    title: `Lesson ${id}`,
    type: "text",
    order: 0,
    is_preview: false,
    completed,
    duration_seconds: null,
    data: { type: "text", body_markdown: "x" },
  } as LessonOut;
}

describe("pickResumeLessonId", () => {
  it("returns null for an empty course", () => {
    expect(pickResumeLessonId([])).toBeNull();
  });

  it("returns the very first lesson when nothing is completed", () => {
    expect(pickResumeLessonId([L("a"), L("b"), L("c")])).toBe("a");
  });

  it("skips completed lessons and returns the first unfinished", () => {
    // Core "Continue learning" behaviour: drop the learner at the next
    // thing they haven't done, not at lesson 1 every time.
    expect(
      pickResumeLessonId([L("a", true), L("b", true), L("c"), L("d")]),
    ).toBe("c");
  });

  it("falls back to the first lesson when every lesson is completed", () => {
    // Course is fully done — no "next" exists. Land on lesson 1 so the
    // learner can re-review rather than seeing an empty player.
    expect(pickResumeLessonId([L("a", true), L("b", true)])).toBe("a");
  });

  it("handles a course with only one lesson", () => {
    expect(pickResumeLessonId([L("only")])).toBe("only");
    expect(pickResumeLessonId([L("only", true)])).toBe("only");
  });
});
