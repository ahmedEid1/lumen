import { describe, expect, it } from "vitest";
import { BACKOFF_STEPS_MS, nextBackoff, shouldRetry } from "@/lib/reconnect";

describe("nextBackoff", () => {
  it("returns the schedule step for each attempt", () => {
    expect(nextBackoff(0)).toBe(1_000);
    expect(nextBackoff(1)).toBe(2_000);
    expect(nextBackoff(2)).toBe(4_000);
  });

  it("clamps to the last step beyond the schedule", () => {
    const last = BACKOFF_STEPS_MS[BACKOFF_STEPS_MS.length - 1];
    expect(nextBackoff(99)).toBe(last);
    expect(nextBackoff(1_000_000)).toBe(last);
  });

  it("treats negative attempts as the first step", () => {
    expect(nextBackoff(-1)).toBe(1_000);
  });
});

describe("shouldRetry", () => {
  it("retries on undefined / 1006 / network drops", () => {
    expect(shouldRetry(undefined)).toBe(true);
    expect(shouldRetry(1006)).toBe(true);
    expect(shouldRetry(1011)).toBe(true);
  });

  it("does not retry on server-refused codes", () => {
    expect(shouldRetry(4401)).toBe(false); // unauthenticated
    expect(shouldRetry(4403)).toBe(false); // forbidden
    expect(shouldRetry(4404)).toBe(false); // course gone
  });
});
