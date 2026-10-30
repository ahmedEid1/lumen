/**
 * L47 — the footer links the owner's portfolio.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SiteFooter } from "@/components/shared/site-footer";

describe("SiteFooter", () => {
  it("links 'Built by Ahmed Hobeishy' to the portfolio", () => {
    render(<SiteFooter />);
    expect(
      screen.getByRole("link", { name: "Built by Ahmed Hobeishy" }),
    ).toHaveAttribute("href", "https://ahmedhobeishy.tech");
  });
});
