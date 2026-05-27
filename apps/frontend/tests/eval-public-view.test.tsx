/**
 * L27 — public /eval surface.
 *
 * Asserts the surface renders the honest-empty state (no fake
 * numbers) + the canonical worked example + the closing
 * methodology / contact CTAs. The page reads no data today; once
 * a sealed admin-promoted run lands, this test grows.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { EvalPublicView } from "@/app/eval/eval-public-view";

describe("EvalPublicView", () => {
  it("renders the headline and sealed-run-pending banner", () => {
    render(<EvalPublicView />);
    expect(screen.getByText("Public eval")).toBeInTheDocument();
    expect(
      screen.getByText(/How the tutor scores. Receipts only./i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("eval-sealed-pending")).toHaveTextContent(
      /first sealed run pending/i,
    );
  });

  it("renders the canonical worked example with the tool path", () => {
    render(<EvalPublicView />);
    expect(
      screen.getByText(/canonical demo question, end-to-end/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Type 'string' is not assignable to type 'T'/i)).toBeInTheDocument();
    expect(screen.getByText("retriever")).toBeInTheDocument();
    expect(screen.getByText("code_runner")).toBeInTheDocument();
  });

  it("renders the methodology link + contact CTA in the footer", () => {
    render(<EvalPublicView />);
    expect(
      screen.getByRole("link", { name: /Methodology/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Email me/i })).toBeInTheDocument();
  });

  it("does NOT render fake numbers when no sealed run exists", () => {
    render(<EvalPublicView />);
    // No "4.10 / 5" or similar score numbers should appear.
    expect(screen.queryByText(/\d\.\d{2} \/ 5/)).not.toBeInTheDocument();
    expect(screen.queryByText(/refusal rate: \d+%/i)).not.toBeInTheDocument();
  });
});
