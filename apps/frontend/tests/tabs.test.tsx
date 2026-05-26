/**
 * Loop 14 — Tabs primitive coverage.
 *
 * Asserts the Radix-backed contract /studio + /admin/observability
 * migrations rely on:
 *   - role="tablist" / role="tab" / role="tabpanel"
 *   - aria-selected toggles with active state
 *   - controlled value + onValueChange
 *   - Trigger click switches active content
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

function Example({ onValueChange }: { onValueChange?: (v: string) => void } = {}) {
  const [v, setV] = useState("a");
  return (
    <Tabs
      value={v}
      onValueChange={(nv) => {
        setV(nv);
        onValueChange?.(nv);
      }}
    >
      <TabsList aria-label="Test tabs">
        <TabsTrigger value="a">Alpha</TabsTrigger>
        <TabsTrigger value="b">Beta</TabsTrigger>
        <TabsTrigger value="c">Gamma</TabsTrigger>
      </TabsList>
      <TabsContent value="a">Body Alpha</TabsContent>
      <TabsContent value="b">Body Beta</TabsContent>
      <TabsContent value="c">Body Gamma</TabsContent>
    </Tabs>
  );
}

describe("Tabs primitive", () => {
  it("renders TabsList as role=tablist", () => {
    render(<Example />);
    expect(screen.getByRole("tablist", { name: "Test tabs" })).toBeInTheDocument();
  });

  it("renders triggers as role=tab with aria-selected on the active one", () => {
    render(<Example />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("aria-selected", "false");
  });

  it("renders the active content + hides the others", () => {
    render(<Example />);
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Body Alpha");
    expect(screen.queryByText("Body Beta")).not.toBeInTheDocument();
  });

  it("switches active content on trigger click", async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole("tab", { name: "Beta" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Body Beta");
  });

  it("fires onValueChange with the new value", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Example onValueChange={onValueChange} />);
    await user.click(screen.getByRole("tab", { name: "Gamma" }));
    expect(onValueChange).toHaveBeenCalledWith("c");
  });
});
