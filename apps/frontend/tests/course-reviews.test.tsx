import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CourseReviews } from "@/components/course/course-reviews";
import { en } from "@/lib/i18n/messages/en";
import type { CourseDetail, ReviewOut } from "@/lib/api/types";

// CourseReviews mounts <MyReviewEditor> (which needs a QueryClient) only when a
// signed-in, enrolled, non-owner viewer is present. Passing `user={null}`
// isolates the reviews list — the surface that renders reviewer names — without
// pulling in the editor's TanStack Query dependency.
const baseCourse: CourseDetail = {
  id: "c1",
  title: "FastAPI from Zero",
  slug: "fastapi-from-zero",
  overview: "Build a tiny API.",
  difficulty: "beginner",
  cover_url: null,
  status: "published",
  visibility: "public",
  moderation_state: null,
  is_featured: false,
  published_at: "2026-05-01T00:00:00Z",
  created_at: "2026-05-01T00:00:00Z",
  owner: { id: "u1", full_name: "Tareq", avatar_url: null, bio: null, role: "instructor" },
  subject: { id: "s1", title: "Programming", slug: "programming", total_courses: 0 },
  tags: [],
  modules_count: 3,
  enrollments_count: 42,
  avg_rating: 4.5,
  origin: null,
  is_clone: false,
  modules: [],
  is_enrolled: false,
  progress_pct: 0,
  is_publicly_listed: true,
  can_publish_public: null,
  learning_outcomes: [],
};

function review(over: Partial<ReviewOut>): ReviewOut {
  return {
    id: "r1",
    rating: 4,
    body: "Solid course.",
    created_at: "2026-05-02T00:00:00Z",
    updated_at: "2026-05-02T00:00:00Z",
    author: { id: "a1", full_name: "Lina", avatar_url: null, bio: null, role: "user" },
    ...over,
  };
}

describe("CourseReviews", () => {
  it("renders a reviewer's live name and body", () => {
    render(<CourseReviews course={baseCourse} reviews={[review({})]} user={null} />);
    expect(screen.getByText("Lina")).toBeInTheDocument();
    expect(screen.getByText("Solid course.")).toBeInTheDocument();
  });

  // S6.10 / DR-19 read-time anonymization (S7 Gate-B): a tombstoned reviewer's
  // `full_name` arrives as the i18n KEY "common.deletedUser"; the list must
  // resolve it to the localized label, never paint the raw key.
  it("renders the localized deleted-user label for a tombstoned reviewer", () => {
    render(
      <CourseReviews
        course={baseCourse}
        reviews={[
          review({
            id: "r2",
            author: {
              id: "gone",
              full_name: "common.deletedUser",
              avatar_url: null,
              bio: null,
              role: "user",
            },
          }),
        ]}
        user={null}
      />,
    );
    expect(screen.getByText(en["common.deletedUser"])).toBeInTheDocument();
    expect(screen.queryByText("common.deletedUser")).not.toBeInTheDocument();
  });
});
