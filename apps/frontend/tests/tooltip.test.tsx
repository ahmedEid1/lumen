/**
 * Loop 12 — Tooltip primitive coverage.
 *
 * Asserts the Radix-backed contract:
 *   - Focus on trigger → tooltip appears with role="tooltip"
 *   - data-wb-tooltip-content present (drives the fade-in rule)
 *   - Escape closes
 *   - Renders nothing initially
 *
 * Hover triggers (`userEvent.hover`) are real-browser-only in
 * practice — happy-dom's pointer-event simulation is partial. We
 * lean on focus-based assertions (Radix supports both identically).
 * Real hover behaviour is covered by Playwright e2e + axe-core.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

function ExampleTooltip() {
  return (
    <TooltipProvider delayDuration={0} skipDelayDuration={0}>
      <Tooltip>
        <TooltipTrigger>Trigger</TooltipTrigger>
        <TooltipContent>Hint text</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

describe("Tooltip primitive", () => {
  it("renders nothing initially", () => {
    render(<ExampleTooltip />);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.queryByText("Hint text")).not.toBeInTheDocument();
  });

  it("shows tooltip on focus", async () => {
    const user = userEvent.setup();
    render(<ExampleTooltip />);
    const trigger = screen.getByText("Trigger");
    await user.tab(); // focus the trigger
    expect(trigger).toHaveFocus();
    // Radix renders BOTH a visible content card AND an sr-only span
    // with role="tooltip" (the accessible-name source). Both carry
    // the same text — assert against the role-tagged one.
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Hint text");
  });

  it("attaches data-wb-tooltip-content for the open-animation hook", async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider delayDuration={0} skipDelayDuration={0}>
        <Tooltip>
          <TooltipTrigger>T</TooltipTrigger>
          <TooltipContent data-testid="tooltip-content">x</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    await user.tab();
    const content = await screen.findByTestId("tooltip-content");
    expect(content).toHaveAttribute("data-wb-tooltip-content");
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ExampleTooltip />);
    await user.tab();
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
