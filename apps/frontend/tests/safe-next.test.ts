import { describe, expect, it } from "vitest";
import { safeNext } from "@/lib/auth/safe-next";

// QA-loop iter 1 / Codex rescue #1: lock the open-redirect guard
// behaviour so a future refactor can't quietly drop the same-origin
// check on the login page's `?next=` query.

describe("safeNext", () => {
  it("falls back to /dashboard when next is missing", () => {
    expect(safeNext(null)).toBe("/dashboard");
    expect(safeNext(undefined)).toBe("/dashboard");
    expect(safeNext("")).toBe("/dashboard");
  });

  it("passes through same-origin relative paths", () => {
    expect(safeNext("/dashboard")).toBe("/dashboard");
    expect(safeNext("/learn/typescript-variance")).toBe("/learn/typescript-variance");
    expect(safeNext("/learn/foo?tutor=open&q=bar")).toBe("/learn/foo?tutor=open&q=bar");
  });

  it("blocks protocol-relative URLs", () => {
    expect(safeNext("//attacker.example")).toBe("/dashboard");
    expect(safeNext("//attacker.example/path")).toBe("/dashboard");
  });

  it("blocks Windows-style traversal", () => {
    expect(safeNext("/\\attacker.example")).toBe("/dashboard");
  });

  it("blocks absolute URLs", () => {
    expect(safeNext("https://attacker.example")).toBe("/dashboard");
    expect(safeNext("http://attacker.example")).toBe("/dashboard");
    expect(safeNext("javascript:alert(1)")).toBe("/dashboard");
    expect(safeNext("data:text/html,<script>alert(1)</script>")).toBe("/dashboard");
  });

  it("blocks bare paths without leading slash", () => {
    expect(safeNext("dashboard")).toBe("/dashboard");
    expect(safeNext("attacker.example")).toBe("/dashboard");
  });
});
