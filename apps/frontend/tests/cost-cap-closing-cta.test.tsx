/**
 * L23 — Cost-cap closing CTA.
 *
 * Asserts:
 * - `isCostCapError()` returns true for each cost-cap error code +
 *   for messages that include the snake-case identifier.
 * - The component renders the locked copy + the email-me / book-call
 *   CTAs.
 * - `resetsIn` line renders only when a future `resetAt` is provided.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  CostCapClosingCta,
  isCostCapError,
} from "@/components/tutor/cost-cap-closing-cta";

describe("isCostCapError", () => {
  it("matches each of the canonical error codes on the error object", () => {
    expect(isCostCapError({ code: "llm.budget_exceeded" })).toBe(true);
    expect(isCostCapError({ code: "tutor.user_cap" })).toBe(true);
    expect(isCostCapError({ code: "tutor.ip_cap" })).toBe(true);
    expect(isCostCapError({ code: "tutor.global_cap" })).toBe(true);
  });

  it("matches when the code is inside Error.message (fallback)", () => {
    expect(isCostCapError(new Error("(429) llm.budget_exceeded"))).toBe(true);
    expect(isCostCapError(new Error("got tutor.user_cap from server"))).toBe(
      true,
    );
  });

  it("returns false for unrelated errors", () => {
    expect(isCostCapError(null)).toBe(false);
    expect(isCostCapError(undefined)).toBe(false);
    expect(isCostCapError(new Error("Network is offline"))).toBe(false);
    expect(isCostCapError({ code: "tutor.streaming_disabled" })).toBe(false);
  });
});

describe("CostCapClosingCta", () => {
  it("renders the locked copy", () => {
    render(<CostCapClosingCta />);
    expect(screen.getByText("Demo budget reached")).toBeInTheDocument();
    expect(
      screen.getByText(/used today.s share of the demo budget/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Email me/i }),
    ).toBeInTheDocument();
  });

  it("renders the reset timer when resetAt is in the future", () => {
    const futureReset = new Date(Date.now() + 5 * 60 * 60 * 1000);
    render(<CostCapClosingCta resetAt={futureReset} />);
    expect(screen.getByText(/Resets in/)).toBeInTheDocument();
  });

  it("hides the reset timer when resetAt is in the past", () => {
    const pastReset = new Date(Date.now() - 1000);
    render(<CostCapClosingCta resetAt={pastReset} />);
    expect(screen.queryByText(/Resets in/)).not.toBeInTheDocument();
  });

  it("renders the book-a-call CTA only when a calendlyUrl is supplied", () => {
    const { rerender } = render(<CostCapClosingCta />);
    expect(
      screen.queryByRole("link", { name: /Book a call/i }),
    ).not.toBeInTheDocument();

    rerender(<CostCapClosingCta calendlyUrl="https://calendly.test" />);
    expect(
      screen.getByRole("link", { name: /Book a call/i }),
    ).toBeInTheDocument();
  });
});
