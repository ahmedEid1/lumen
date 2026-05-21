import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "@/components/ui/badge";

describe("Badge", () => {
  it("renders the children", () => {
    render(<Badge>Featured</Badge>);
    expect(screen.getByText("Featured")).toBeInTheDocument();
  });

  it("applies the default variant when none is given", () => {
    render(<Badge data-testid="b">x</Badge>);
    expect(screen.getByTestId("b").className).toMatch(/bg-primary/);
  });

  it("switches to secondary styles for the secondary variant", () => {
    render(
      <Badge data-testid="b" variant="secondary">
        y
      </Badge>,
    );
    expect(screen.getByTestId("b").className).toMatch(/bg-secondary/);
  });
});
