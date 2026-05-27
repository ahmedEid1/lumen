/**
 * L30 — /case-study smoke test.
 *
 * The page is content-heavy + text-only. The render-boundary check
 * is what matters: confirm the cartouches + the architecture-sketch
 * svg + the closing CTAs all render. Per-paragraph copy is verified
 * by i18n parity, not by this test.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CaseStudyView } from "@/app/case-study/case-study-view";

describe("CaseStudyView", () => {
  it("renders the headline + 6 section cartouches", () => {
    render(<CaseStudyView />);
    expect(
      screen.getByRole("heading", { level: 1, name: /built an agentic tutor/i }),
    ).toBeInTheDocument();
    // Cartouche text appears in the section header AND once in the
    // breadcrumb-style label. getAllByText catches both; we just
    // want >= 1 occurrence.
    expect(screen.getAllByText(/Origin/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Architecture/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Anatomy of one turn/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Prompt iteration/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/What I did not use/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Lessons/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the architecture sketch as a labeled svg", () => {
    render(<CaseStudyView />);
    const svg = screen.getByRole("img", {
      name: /Lumen architecture/i,
    });
    expect(svg).toBeInTheDocument();
    expect(svg.tagName.toLowerCase()).toBe("svg");
  });

  it("renders the closing CTAs (demo, eval, email)", () => {
    render(<CaseStudyView />);
    expect(
      screen.getByRole("link", { name: /Try the demo/i }),
    ).toHaveAttribute("href", "/demo");
    expect(
      screen.getByRole("link", { name: /Read the evals/i }),
    ).toHaveAttribute("href", "/eval");
    expect(screen.getByRole("link", { name: /Email me/i })).toBeInTheDocument();
  });
});
