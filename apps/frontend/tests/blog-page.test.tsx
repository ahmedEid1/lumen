/**
 * L19.5 — empty /blog index renders the EmptyState + headline.
 *
 * Smoke test only — once posts land (L30+), this spec grows.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { BlogIndex } from "@/app/blog/blog-index";

describe("Blog index page", () => {
  it("renders the cartouche + headline + subline", () => {
    render(<BlogIndex />);
    expect(screen.getByText("Field notes")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: /notes from building lumen/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/architecture decisions, prompt-iteration journals/i),
    ).toBeInTheDocument();
  });

  it("shows the EmptyState until posts exist", () => {
    render(<BlogIndex />);
    expect(screen.getByText("No posts yet.")).toBeInTheDocument();
    expect(
      screen.getByText(/first entries will trail the case study/i),
    ).toBeInTheDocument();
  });
});
