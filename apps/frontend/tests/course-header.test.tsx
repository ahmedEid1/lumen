import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CourseHeader } from "@/components/course/course-header";
import { en } from "@/lib/i18n/messages/en";
import type { CourseDetail } from "@/lib/api/types";

// CourseHeader is a pure presentational component over a CourseDetail. The
// global i18n provider mock (tests/setup.ts) returns real English copy for a
// key, so accessibility-name + text assertions read the live strings. The
// nested <OriginAttribution> renders nothing when `origin` is null, so these
// fixtures keep `origin: null` to isolate the header's own owner row.
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

describe("CourseHeader", () => {
  it("renders the title, overview, and live owner name", () => {
    render(<CourseHeader course={baseCourse} />);
    expect(screen.getByRole("heading", { name: "FastAPI from Zero" })).toBeInTheDocument();
    expect(screen.getByText("Build a tiny API.")).toBeInTheDocument();
    expect(screen.getByText("Tareq")).toBeInTheDocument();
  });

  // S6.10 / DR-19 read-time anonymization (S7 Gate-B): a tombstoned owner's
  // `full_name` arrives as the i18n KEY "common.deletedUser"; the header must
  // resolve it to the localized label rather than paint the raw key.
  it("renders the localized deleted-user label for a tombstoned owner", () => {
    render(
      <CourseHeader
        course={{
          ...baseCourse,
          owner: { ...baseCourse.owner, full_name: "common.deletedUser" },
        }}
      />,
    );
    expect(screen.getByText(en["common.deletedUser"])).toBeInTheDocument();
    expect(screen.queryByText("common.deletedUser")).not.toBeInTheDocument();
  });
});
