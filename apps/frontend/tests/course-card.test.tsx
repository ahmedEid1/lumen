import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CourseCard } from "@/components/course/course-card";
import type { CourseListItem } from "@/lib/api/types";

const sample: CourseListItem = {
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
    render(<CourseCard course={sample} />);
    expect(screen.getByText("FastAPI from Zero")).toBeInTheDocument();
    expect(screen.getByText("Tareq")).toBeInTheDocument();
    expect(screen.getByText("3 modules")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("4.5")).toBeInTheDocument();
    expect(screen.getByText("Featured")).toBeInTheDocument();
  });

  it("links to the slug", () => {
    render(<CourseCard course={sample} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/courses/fastapi-from-zero");
  });
});
