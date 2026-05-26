/**
 * Loop 13 — Select primitive coverage.
 *
 * Pins the Radix-backed contract the studio/admin/profile/lesson-
 * editor migrations now rely on:
 *   - Trigger opens content
 *   - Items render with role="option"
 *   - onValueChange fires on selection
 *   - Escape closes
 *   - data-wb-select-content marker drives the fade-in rule
 *
 * Arrow-key navigation is Radix-handled and exercised by Playwright +
 * axe-core. happy-dom doesn't simulate Radix's roving focus reliably.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

function ExampleSelect({ onValueChange }: { onValueChange?: (v: string) => void } = {}) {
  const [value, setValue] = useState("");
  return (
    <Select
      value={value}
      onValueChange={(v) => {
        setValue(v);
        onValueChange?.(v);
      }}
    >
      <SelectTrigger>
        <SelectValue placeholder="Pick one" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="a">Alpha</SelectItem>
        <SelectItem value="b">Beta</SelectItem>
        <SelectItem value="c">Gamma</SelectItem>
      </SelectContent>
    </Select>
  );
}

describe("Select primitive", () => {
  it("renders trigger with placeholder when no value", () => {
    render(<ExampleSelect />);
    expect(screen.getByText("Pick one")).toBeInTheDocument();
  });

  it("opens content on click + renders items as role=option", async () => {
    const user = userEvent.setup();
    render(<ExampleSelect />);
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    await user.click(screen.getByRole("combobox"));
    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(3);
    expect(options[0]).toHaveTextContent("Alpha");
  });

  it("fires onValueChange when an item is clicked", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<ExampleSelect onValueChange={onValueChange} />);
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Beta" }));
    expect(onValueChange).toHaveBeenCalledWith("b");
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ExampleSelect />);
    await user.click(screen.getByRole("combobox"));
    await screen.findAllByRole("option");
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("attaches data-wb-select-content for the open-animation hook", async () => {
    const user = userEvent.setup();
    render(<ExampleSelect />);
    await user.click(screen.getByRole("combobox"));
    const opts = await screen.findAllByRole("option");
    // The Content element is an ancestor of the options — find the
    // nearest ancestor with the marker.
    let el: HTMLElement | null = opts[0];
    while (el && !el.hasAttribute("data-wb-select-content")) {
      el = el.parentElement;
    }
    expect(el).not.toBeNull();
  });

  it("trigger has role=combobox (Radix Select convention per WAI-ARIA)", () => {
    render(<ExampleSelect />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });
});
