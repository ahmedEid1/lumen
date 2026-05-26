/**
 * Loop 11 — Popover primitive coverage.
 *
 * Validates the contract notifications-bell now relies on:
 *   - Trigger opens the popover
 *   - PopoverContent renders inside a Radix portal (so positioning
 *     doesn't fight ancestor overflow)
 *   - Escape closes
 *   - DialogClose-equivalent path (controlled mode) works
 *   - Custom data-wb-popover-content marker is set (drives the
 *     fade-in animation rule in globals.css)
 *
 * Focus-trap + click-outside are Radix-handled and exercised by the
 * Playwright e2e + axe-core CI gate, not happy-dom.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

function ExamplePopover() {
  return (
    <Popover>
      <PopoverTrigger>Open popover</PopoverTrigger>
      <PopoverContent>
        <p>Popover body</p>
      </PopoverContent>
    </Popover>
  );
}

function ControlledPopover() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>External open</button>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger>Trigger</PopoverTrigger>
        <PopoverContent>
          <button onClick={() => setOpen(false)}>External close</button>
        </PopoverContent>
      </Popover>
    </>
  );
}

describe("Popover primitive", () => {
  it("renders trigger and opens content on click", async () => {
    const user = userEvent.setup();
    render(<ExamplePopover />);
    expect(screen.queryByText("Popover body")).not.toBeInTheDocument();
    await user.click(screen.getByText("Open popover"));
    expect(await screen.findByText("Popover body")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ExamplePopover />);
    await user.click(screen.getByText("Open popover"));
    expect(await screen.findByText("Popover body")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByText("Popover body")).not.toBeInTheDocument();
  });

  it("supports controlled open via onOpenChange", async () => {
    const user = userEvent.setup();
    render(<ControlledPopover />);
    expect(screen.queryByText("External close")).not.toBeInTheDocument();
    await user.click(screen.getByText("External open"));
    expect(await screen.findByText("External close")).toBeInTheDocument();
    await user.click(screen.getByText("External close"));
    expect(screen.queryByText("External close")).not.toBeInTheDocument();
  });

  it("attaches data-wb-popover-content for the open-animation hook", async () => {
    render(
      <Popover defaultOpen>
        <PopoverTrigger>T</PopoverTrigger>
        <PopoverContent data-testid="popover-content">
          <p>x</p>
        </PopoverContent>
      </Popover>,
    );
    const content = await screen.findByTestId("popover-content");
    expect(content).toHaveAttribute("data-wb-popover-content");
  });

  it("respects custom align prop (positions content via data-align)", async () => {
    render(
      <Popover defaultOpen>
        <PopoverTrigger>T</PopoverTrigger>
        <PopoverContent align="start" data-testid="popover-content">
          <p>x</p>
        </PopoverContent>
      </Popover>,
    );
    const content = await screen.findByTestId("popover-content");
    // Radix uses data-align="start|center|end" on the rendered Content
    expect(content).toHaveAttribute("data-align", "start");
  });
});
