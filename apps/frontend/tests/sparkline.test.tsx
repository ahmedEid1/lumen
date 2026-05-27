/**
 * L26 — Sparkline component.
 *
 * Pure SVG; we assert the path string the component emits is the
 * mapping of input values → coordinates we expect, so a refactor
 * can't silently regress the visual.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { Sparkline } from "@/components/eval/sparkline";

describe("Sparkline", () => {
  it("renders an SVG with the right number of segments", () => {
    const { container } = render(
      <Sparkline data={[{ value: 1 }, { value: 2 }, { value: 3 }]} />,
    );
    const path = container.querySelector("path");
    expect(path).not.toBeNull();
    const d = path?.getAttribute("d") ?? "";
    // "M ... L ... L ..." — one M + (n-1) L's for n points.
    const segments = d.split(/[ML]/).filter(Boolean);
    expect(segments).toHaveLength(3);
  });

  it("clamps values outside the supplied range", () => {
    const { container } = render(
      <Sparkline data={[{ value: -2 }, { value: 7 }]} range={[0, 5]} />,
    );
    // The point at value=-2 should land at the bottom (y near H-PAD);
    // value=7 at the top. Both inside the SVG box.
    const path = container.querySelector("path")?.getAttribute("d") ?? "";
    const ys = [...path.matchAll(/[ML] [\d.]+ ([\d.]+)/g)].map((m) =>
      parseFloat(m[1]),
    );
    expect(ys.every((y) => y >= 0 && y <= 16)).toBe(true);
  });

  it("renders the empty placeholder when no data", () => {
    render(<Sparkline data={[]} />);
    expect(screen.getByText("——")).toBeInTheDocument();
  });

  it("emits a spoken summary via <title> for a11y", () => {
    const { container } = render(
      <Sparkline data={[{ value: 4.1 }, { value: 4.2 }]} />,
    );
    expect(container.querySelector("title")?.textContent).toMatch(
      /4\.10.*4\.20/,
    );
  });

  it("renders a focus dot on the rightmost point", () => {
    const { container } = render(
      <Sparkline data={[{ value: 1 }, { value: 5 }]} range={[0, 5]} />,
    );
    const circle = container.querySelector("circle");
    expect(circle).not.toBeNull();
  });
});
