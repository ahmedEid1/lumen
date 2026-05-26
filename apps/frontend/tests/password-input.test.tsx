/**
 * Loop 15 — PasswordInput coverage.
 *
 * - Default renders as type="password"
 * - Eye toggle button is reachable + has translated aria-label
 * - Clicking toggle flips type → "text" and aria-label flips
 * - Value preserved across toggle
 * - aria-pressed reflects toggle state
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { PasswordInput } from "@/components/ui/password-input";

function Controlled({ initial = "" }: { initial?: string } = {}) {
  const [v, setV] = useState(initial);
  return (
    <PasswordInput
      id="pw"
      value={v}
      onChange={(e) => setV(e.target.value)}
      aria-label="Password"
    />
  );
}

describe("PasswordInput primitive", () => {
  it("renders the input as type=password by default", () => {
    render(<Controlled />);
    const input = screen.getByLabelText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");
  });

  it("exposes a toggle button with 'Show password' aria-label", () => {
    render(<Controlled />);
    expect(
      screen.getByRole("button", { name: /show password/i }),
    ).toBeInTheDocument();
  });

  it("flips input type and aria-label on toggle click", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");
    await user.click(screen.getByRole("button", { name: /show password/i }));
    expect(input.type).toBe("text");
    expect(
      screen.getByRole("button", { name: /hide password/i }),
    ).toBeInTheDocument();
  });

  it("preserves the entered value across the toggle", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText("Password") as HTMLInputElement;
    await user.type(input, "Secret!2026");
    expect(input.value).toBe("Secret!2026");
    await user.click(screen.getByRole("button", { name: /show password/i }));
    expect(input.value).toBe("Secret!2026");
    await user.click(screen.getByRole("button", { name: /hide password/i }));
    expect(input.value).toBe("Secret!2026");
  });

  it("aria-pressed reflects the toggle state", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const btn = screen.getByRole("button", { name: /show password/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    await user.click(btn);
    expect(
      screen.getByRole("button", { name: /hide password/i }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
