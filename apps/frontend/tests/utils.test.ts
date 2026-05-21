import { describe, expect, it } from "vitest";
import { cn, formatRelative, pluralize } from "@/lib/utils";

describe("cn", () => {
  it("merges class names and dedupes tailwind conflicts", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-sm", false && "hidden", "font-bold")).toBe("text-sm font-bold");
  });
});

describe("pluralize", () => {
  it("returns singular when n=1", () => {
    expect(pluralize(1, "module")).toBe("1 module");
  });
  it("returns plural otherwise", () => {
    expect(pluralize(0, "module")).toBe("0 modules");
    expect(pluralize(3, "module")).toBe("3 modules");
  });
  it("uses explicit plural", () => {
    expect(pluralize(3, "child", "children")).toBe("3 children");
  });
});

describe("formatRelative", () => {
  it("returns 'just now' for sub-minute", () => {
    expect(formatRelative(new Date())).toBe("just now");
  });
  it("returns minutes/hours/days for larger deltas", () => {
    const now = Date.now();
    expect(formatRelative(new Date(now - 5 * 60_000))).toBe("5m ago");
    expect(formatRelative(new Date(now - 5 * 3_600_000))).toBe("5h ago");
    expect(formatRelative(new Date(now - 2 * 86_400_000))).toBe("2d ago");
  });
});
