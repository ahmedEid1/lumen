import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CourseCard } from "@/components/course/course-card";
import type { CourseListItem } from "@/lib/api/types";

const baseSample: CourseListItem = {
  id: "c1",
  title: "FastAPI from Zero",
  slug: "fastapi-from-zero",
  overview: "Build a tiny API.",
  difficulty: "beginner",
  cover_url: null,
  status: "published",
  is_featured: true,
  published_at: "2026-05-01T00:00:00Z",
  created_at: "2026-05-01T00:00:00Z",
  owner: { id: "u1", full_name: "Tareq", avatar_url: null, bio: null, role: "instructor" },
  subject: { id: "s1", title: "Programming", slug: "programming" },
  tags: [{ id: "t1", name: "Python", slug: "python" }],
  modules_count: 3,
  enrollments_count: 42,
  avg_rating: 4.5,
};

describe("CourseCard", () => {
  it("renders the course title, owner, and stats", () => {
    render(<CourseCard course={baseSample} />);
    expect(screen.getByText("FastAPI from Zero")).toBeInTheDocument();
    expect(screen.getByText("Tareq")).toBeInTheDocument();
    expect(screen.getByText("3 modules")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("4.5")).toBeInTheDocument();
    expect(screen.getByText("Featured")).toBeInTheDocument();
  });

  it("links to the slug", () => {
    render(<CourseCard course={baseSample} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/courses/fastapi-from-zero");
  });

  it("hides the Featured badge when is_featured is false", () => {
    render(<CourseCard course={{ ...baseSample, is_featured: false }} />);
    expect(screen.queryByText("Featured")).not.toBeInTheDocument();
  });

  it("omits the rating tile when avg_rating is null", () => {
    render(<CourseCard course={{ ...baseSample, avg_rating: null }} />);
    expect(screen.queryByText("4.5")).not.toBeInTheDocument();
  });

  it("renders the cover image when cover_url is provided", () => {
    render(
      <CourseCard course={{ ...baseSample, cover_url: "https://cdn.test/cover.jpg" }} />,
    );
    const img = document.querySelector('img[src="https://cdn.test/cover.jpg"]');
    expect(img).not.toBeNull();
  });

  it("renders a decorative glyph fallback when there is no cover image", () => {
    const { container } = render(<CourseCard course={baseSample} />);
    // No <img> when cover_url is null
    expect(container.querySelector("img")).toBeNull();
    // The empty-cover area contains an SVG glyph — keyed to the scroll
    // motif from the lumen primitives. We assert there is *some* SVG
    // rather than pin a viewBox, so future glyph swaps don't break.
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("renders the difficulty + subject badges", () => {
    render(<CourseCard course={baseSample} />);
    expect(screen.getByText("Programming")).toBeInTheDocument();
    expect(screen.getByText("beginner")).toBeInTheDocument();
  });
});
