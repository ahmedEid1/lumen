import { describe, expect, it } from "vitest";
import { en } from "../src/lib/i18n/messages/en";
import { ar } from "../src/lib/i18n/messages/ar";

// Iter 104 regression: the LocaleSwitcher's `aria-label` is
// `${t("common.language")}: ${LOCALE_LABELS[locale]}`, so it
// localises along with the rest of the UI. The e2e
// "language switcher toggles document direction" spec needs to
// match the label in BOTH English and Arabic — the first click
// matches the EN label, the second (page is now AR) matches
// the AR label. The spec uses `getByLabel(/language|اللغة/i)`;
// this test pins the two literals so neither key can be
// renamed without breaking the e2e regex in lockstep.
//
// If you rename `common.language` in messages, update the e2e
// regex in tests/e2e/learner-journey.spec.ts:71 to match.

describe("LocaleSwitcher aria-label literals are stable", () => {
  it("EN `common.language` is exactly 'Language'", () => {
    expect(en["common.language"]).toBe("Language");
  });

  it("AR `common.language` is the Arabic word for language", () => {
    expect(ar["common.language"]).toBe("اللغة");
  });
});
