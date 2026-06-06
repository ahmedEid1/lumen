/**
 * S1.11 — useCapabilities / capabilitiesFor (ADR-0025 two-role model).
 *
 * Pure derivation tests over the loaded `/me` user: any active user may
 * author/clone/publish; admin is the only elevated role; a stale legacy role
 * never satisfies `isAdmin`; a suspended user gets nothing.
 */
import { describe, expect, it } from "vitest";
import { capabilitiesFor } from "@/lib/auth/capabilities";
import type { UserOut } from "@/lib/api/types";

function user(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "u1",
    full_name: "U",
    avatar_url: null,
    bio: null,
    role: "user",
    email: "u@lumen.test",
    is_active: true,
    email_verified_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("capabilitiesFor", () => {
  it("anonymous → all false", () => {
    const c = capabilitiesFor(null);
    expect(c).toEqual({ isAdmin: false, canAuthor: false, canPublishPublic: false, canClone: false });
  });

  it("active user → author/clone/publish true, not admin", () => {
    const c = capabilitiesFor(user({ role: "user" }));
    expect(c.canAuthor).toBe(true);
    expect(c.canClone).toBe(true);
    expect(c.canPublishPublic).toBe(true);
    expect(c.isAdmin).toBe(false);
  });

  it("admin → all true including isAdmin", () => {
    const c = capabilitiesFor(user({ role: "admin" }));
    expect(c.isAdmin).toBe(true);
    expect(c.canAuthor).toBe(true);
  });

  it("suspended user → all false (suspension is the revocation axis)", () => {
    const c = capabilitiesFor(user({ is_active: false }));
    expect(c.canAuthor).toBe(false);
    expect(c.isAdmin).toBe(false);
  });

  it("stale legacy role never escalates to admin", () => {
    // A `/me` that still carries a legacy `instructor` claim is an active
    // author, but NOT an admin.
    const c = capabilitiesFor(user({ role: "instructor" as unknown as UserOut["role"] }));
    expect(c.canAuthor).toBe(true);
    expect(c.isAdmin).toBe(false);
  });
});
