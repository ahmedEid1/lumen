import { describe, expect, it } from "vitest";
import { en } from "@/lib/i18n/messages/en";
import { ar } from "@/lib/i18n/messages/ar";

describe("i18n message parity", () => {
  // English is the source of truth — every key here must exist in
  // every other locale. Adding a translation: paste the new key into
  // en.ts AND ar.ts. The Record<MessageKey, string> type already
  // catches this at compile time; the runtime test is belt-and-
  // suspenders against accidentally using a `Partial` somewhere.
  it("Arabic has the same keys as English", () => {
    const enKeys = Object.keys(en).sort();
    const arKeys = Object.keys(ar).sort();
    expect(arKeys).toEqual(enKeys);
  });

  it("Arabic has no empty strings", () => {
    for (const [k, v] of Object.entries(ar)) {
      expect(v.trim()).not.toBe("");
      expect(v, `arabic translation missing for ${k}`).not.toBe(k);
    }
  });
});
