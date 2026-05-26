/**
 * Loop 11 — DropdownMenu primitive coverage.
 *
 * Validates the contract locale-switcher now relies on:
 *   - Trigger opens the menu
 *   - Item / Label / Separator render with the correct ARIA roles
 *   - RadioGroup + RadioItem express selection via aria-checked
 *   - CheckboxItem toggles aria-checked
 *   - Escape closes
 *
 * Arrow-key navigation and roving-focus are Radix-handled — happy-dom
 * doesn't simulate them faithfully. The Playwright e2e + axe-core
 * gate cover real-browser keyboard behaviour.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function ExampleMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger>Open menu</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Section label</DropdownMenuLabel>
        <DropdownMenuItem>Item one</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem>Item two</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RadioMenu() {
  const [value, setValue] = useState("a");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger>Pick</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuRadioGroup value={value} onValueChange={setValue}>
          <DropdownMenuRadioItem value="a">Alpha</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="b">Beta</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function CheckboxMenu() {
  const [checked, setChecked] = useState(false);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger>Toggle</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuCheckboxItem checked={checked} onCheckedChange={setChecked}>
          Featured
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

describe("DropdownMenu primitive", () => {
  it("renders trigger and opens menu on click", async () => {
    const user = userEvent.setup();
    render(<ExampleMenu />);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await user.click(screen.getByText("Open menu"));
    expect(await screen.findByRole("menu")).toBeInTheDocument();
  });

  it("renders Items with role=menuitem and Label as non-interactive", async () => {
    const user = userEvent.setup();
    render(<ExampleMenu />);
    await user.click(screen.getByText("Open menu"));
    await screen.findByRole("menu");
    expect(screen.getAllByRole("menuitem")).toHaveLength(2);
    // The Label is not a menuitem — it's a heading-like marker.
    expect(
      screen.queryByRole("menuitem", { name: "Section label" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Section label")).toBeInTheDocument();
  });

  it("renders Separator with role=separator", async () => {
    const user = userEvent.setup();
    render(<ExampleMenu />);
    await user.click(screen.getByText("Open menu"));
    await screen.findByRole("menu");
    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ExampleMenu />);
    await user.click(screen.getByText("Open menu"));
    await screen.findByRole("menu");
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("RadioGroup marks the active item aria-checked=true", async () => {
    const user = userEvent.setup();
    render(<RadioMenu />);
    await user.click(screen.getByText("Pick"));
    const items = await screen.findAllByRole("menuitemradio");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveAttribute("aria-checked", "true");
    expect(items[1]).toHaveAttribute("aria-checked", "false");
  });

  it("CheckboxItem toggles aria-checked on click", async () => {
    const user = userEvent.setup();
    render(<CheckboxMenu />);
    await user.click(screen.getByText("Toggle"));
    const item = await screen.findByRole("menuitemcheckbox", { name: /featured/i });
    expect(item).toHaveAttribute("aria-checked", "false");
    await user.click(item);
    // Re-open to inspect — Radix closes on item activation by default.
    await user.click(screen.getByText("Toggle"));
    expect(
      await screen.findByRole("menuitemcheckbox", { name: /featured/i }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("attaches data-wb-dropdown-content for the open-animation hook", async () => {
    const user = userEvent.setup();
    render(<ExampleMenu />);
    await user.click(screen.getByText("Open menu"));
    const menu = await screen.findByRole("menu");
    expect(menu).toHaveAttribute("data-wb-dropdown-content");
  });
});
