/**
 * L29 — landing-page agent-replay hero.
 *
 * Asserts the replay surface renders the canonical question, the one
 * retrieval the live web tutor runs, the cited lesson and the CTAs. Animation is CSS only — we
 * verify it stays inert under prefers-reduced-motion via the
 * inline <style> tag (the rule must reset the animations to none).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { AgentReplayHero } from "@/components/home/agent-replay-hero";

describe("AgentReplayHero", () => {
  it("renders the canonical TS-variance question", () => {
    render(<AgentReplayHero />);
    expect(
      screen.getByText(/^I keep getting .*Type 'string' is not assignable to type 'T'/i),
    ).toBeInTheDocument();
  });

  it("shows only the retriever step the live web tutor runs", () => {
    render(<AgentReplayHero />);
    expect(screen.getByText("retriever")).toBeInTheDocument();
    expect(screen.queryByText("code_runner")).not.toBeInTheDocument();
  });

  it("shows the lesson the answer cites and is captioned as an example", () => {
    render(<AgentReplayHero />);
    expect(screen.getByText(/^The canonical error:/)).toBeInTheDocument();
    expect(screen.getByText("Example run, animated")).toBeInTheDocument();
    expect(screen.queryByText(/live replay/i)).not.toBeInTheDocument();
  });

  it("renders the Try-the-demo and Read-the-evals CTAs", () => {
    render(<AgentReplayHero />);
    expect(screen.getByRole("link", { name: /Try the demo/i })).toHaveAttribute(
      "href",
      "/demo",
    );
    expect(screen.getByRole("link", { name: /Read the evals/i })).toHaveAttribute(
      "href",
      "/eval",
    );
  });

  it("emits prefers-reduced-motion override in the inline <style>", () => {
    const { container } = render(<AgentReplayHero />);
    const styleEl = container.querySelector("style");
    const css = styleEl?.textContent ?? "";
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/animation: none/);
  });

  it("labels the replay panel via role=img + aria-label", () => {
    render(<AgentReplayHero />);
    const panel = screen.getByRole("img");
    expect(panel.getAttribute("aria-label")).toMatch(/animated example/i);
  });
});
