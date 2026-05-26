/**
 * Loop 14 — Breadcrumb primitive coverage.
 *
 * Asserts the semantic-nav contract:
 *   - nav with aria-label="breadcrumb"
 *   - list rendered as <ol>
 *   - links rendered as <a> (or via asChild)
 *   - current page marked aria-current="page" + non-interactive
 *   - separator is decorative (aria-hidden)
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

function Example() {
  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink href="/studio">Studio</BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem>
          <BreadcrumbPage>FastAPI Basics</BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
  );
}

describe("Breadcrumb primitive", () => {
  it("renders nav with aria-label=breadcrumb", () => {
    render(<Example />);
    expect(screen.getByRole("navigation", { name: "breadcrumb" })).toBeInTheDocument();
  });

  it("renders BreadcrumbLink as an <a> with href", () => {
    render(<Example />);
    const link = screen.getByRole("link", { name: "Studio" });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "/studio");
  });

  it("renders BreadcrumbPage with aria-current=page (non-interactive)", () => {
    render(<Example />);
    const page = screen.getByText("FastAPI Basics");
    expect(page).toHaveAttribute("aria-current", "page");
    expect(page).toHaveAttribute("aria-disabled", "true");
  });

  it("renders separator with aria-hidden + role=presentation", () => {
    render(<Example />);
    const list = screen.getByRole("list");
    // The separator is an <li role="presentation">. Find it via its
    // role and aria-hidden.
    const presentations = list.querySelectorAll('[role="presentation"]');
    expect(presentations.length).toBeGreaterThan(0);
    expect(presentations[0]).toHaveAttribute("aria-hidden", "true");
  });
});
