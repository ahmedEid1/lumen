/**
 * Loop 15 — PasswordStrengthMeter coverage.
 *
 * Asserts the scoring heuristic + label rendering.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  PasswordStrengthMeter,
  scorePassword,
} from "@/components/ui/password-strength-meter";

describe("scorePassword heuristic", () => {
  it("empty string → 0", () => {
    expect(scorePassword("")).toBe(0);
  });

  it("short (< 12 chars) → 0", () => {
    expect(scorePassword("abc123")).toBe(0);
  });

  it("12-15 chars with 3+ class diversity → 2 (1 length + 1 diversity)", () => {
    expect(scorePassword("aB3aB3aB3aB3")).toBe(2);
  });

  it("16-19 chars with 4 classes → 3", () => {
    expect(scorePassword("aB3!aB3!aB3!aB3!")).toBe(3);
  });

  it("20+ chars with 4 classes → 4 (capped)", () => {
    expect(scorePassword("aB3!aB3!aB3!aB3!aB3!aaaa")).toBe(4);
  });

  it("all-same chars penalized to 0", () => {
    expect(scorePassword("aaaaaaaaaaaaaaa")).toBe(0);
  });

  it("starts with 'password' → capped at 1", () => {
    expect(scorePassword("Password123!!!!")).toBe(1);
  });
});

describe("PasswordStrengthMeter render", () => {
  it("shows '—' label when value is empty", () => {
    render(<PasswordStrengthMeter value="" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows 'Strong' label for a strong password", () => {
    render(<PasswordStrengthMeter value="aB3!aB3!aB3!aB3!aB3!aaaa" />);
    expect(screen.getByText("Strong")).toBeInTheDocument();
  });

  it("shows 'Weak' label for a 12+ char common-prefix password (penalty-capped)", () => {
    // "Password123!!" is 13 chars with 4 classes (would normally
    // score 2 — 1 length + 1 diversity), but the "password"-prefix
    // penalty caps it at 1 = Weak.
    render(<PasswordStrengthMeter value="Password123!!" />);
    expect(screen.getByText("Weak")).toBeInTheDocument();
  });
});
