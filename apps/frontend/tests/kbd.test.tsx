/**
 * Loop 18 — Kbd primitive coverage.
 *
 * Asserts the semantic `<kbd>` element + Workbench chrome.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Kbd } from "@/components/ui/kbd";

describe("Kbd primitive", () => {
  it("renders as a semantic <kbd> element", () => {
    render(<Kbd>K</Kbd>);
    const el = screen.getByText("K");
    expect(el.tagName).toBe("KBD");
  });

  it("renders its children verbatim", () => {
    render(<Kbd>⌘</Kbd>);
    expect(screen.getByText("⌘")).toBeInTheDocument();
  });

  it("forwards classNames + extra props", () => {
    render(<Kbd className="extra-class" data-testid="kbd-el">K</Kbd>);
    const el = screen.getByTestId("kbd-el");
    expect(el).toHaveClass("extra-class");
  });
});
