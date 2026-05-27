/**
 * L21b — iOS UA sniff coverage.
 *
 * Pin the heuristic: iOS Safari 15.0–15.3 fail; 15.4 and later
 * pass; non-iOS browsers pass.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { supportsStreaming } from "@/lib/tutor/supports-streaming";

const ORIGINAL_UA = navigator.userAgent;

function setUserAgent(ua: string) {
  Object.defineProperty(navigator, "userAgent", {
    value: ua,
    configurable: true,
  });
}

describe("supportsStreaming()", () => {
  beforeEach(() => {
    // happy-dom doesn't define these globally; mock so the feature
    // detect inside the function passes by default.
    (globalThis as { TransformStream?: unknown }).TransformStream ??= class {};
    (globalThis as { TextDecoderStream?: unknown }).TextDecoderStream ??=
      class {};
  });

  afterEach(() => {
    setUserAgent(ORIGINAL_UA);
  });

  it("returns false on iOS Safari 15.0", () => {
    setUserAgent(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
    );
    expect(supportsStreaming()).toBe(false);
  });

  it("returns false on iOS Safari 15.3", () => {
    setUserAgent(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 15_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.3 Mobile/15E148 Safari/604.1",
    );
    expect(supportsStreaming()).toBe(false);
  });

  it("returns true on iOS Safari 15.4", () => {
    setUserAgent(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Mobile/15E148 Safari/604.1",
    );
    expect(supportsStreaming()).toBe(true);
  });

  it("returns true on iOS Safari 17.0", () => {
    setUserAgent(
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    );
    expect(supportsStreaming()).toBe(true);
  });

  it("returns true on desktop Chrome", () => {
    setUserAgent(
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    );
    expect(supportsStreaming()).toBe(true);
  });
});
