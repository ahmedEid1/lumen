/**
 * Loop 13 — Switch primitive coverage.
 *
 * Pins the binary-toggle contract used by lesson "free preview" +
 * admin/courses "featured only":
 *   - Renders as role="switch"
 *   - aria-checked reflects state
 *   - onCheckedChange fires on click + space key
 *   - Disabled prop disables interaction
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Switch } from "@/components/ui/switch";

function ControlledSwitch({
  defaultChecked = false,
  disabled,
  onCheckedChange,
}: {
  defaultChecked?: boolean;
  disabled?: boolean;
  onCheckedChange?: (v: boolean) => void;
} = {}) {
  const [checked, setChecked] = useState(defaultChecked);
  return (
    <Switch
      checked={checked}
      onCheckedChange={(v) => {
        setChecked(v);
        onCheckedChange?.(v);
      }}
      disabled={disabled}
    />
  );
}

describe("Switch primitive", () => {
  it("renders as role=switch", () => {
    render(<ControlledSwitch />);
    expect(screen.getByRole("switch")).toBeInTheDocument();
  });

  it("aria-checked=false by default", () => {
    render(<ControlledSwitch />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("aria-checked=true when checked", () => {
    render(<ControlledSwitch defaultChecked />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("fires onCheckedChange on click", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<ControlledSwitch onCheckedChange={onCheckedChange} />);
    await user.click(screen.getByRole("switch"));
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    await user.click(screen.getByRole("switch"));
    expect(onCheckedChange).toHaveBeenCalledWith(false);
  });

  it("respects disabled prop", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<ControlledSwitch disabled onCheckedChange={onCheckedChange} />);
    const sw = screen.getByRole("switch");
    expect(sw).toBeDisabled();
    await user.click(sw);
    expect(onCheckedChange).not.toHaveBeenCalled();
  });

  it("toggles on space key when focused", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<ControlledSwitch onCheckedChange={onCheckedChange} />);
    await user.tab();
    expect(screen.getByRole("switch")).toHaveFocus();
    await user.keyboard(" ");
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });
});
