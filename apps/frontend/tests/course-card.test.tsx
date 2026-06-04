import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CourseCard } from "@/components/course/course-card";
import { en } from "@/lib/i18n/messages/en";
import type { CourseListItem } from "@/lib/api/types";

// The card derives the clone CTA from `useCapabilities()` (→ `useAuth`),
// which throws outside an AuthProvider. Mock the auth store to a signed-in
// active `user` by default; the anonymous case overrides `user` to null.
const authState = {
  user: {
    id: "u9",
    full_name: "Viewer",
    avatar_url: null,
    bio: null,
    role: "user",
    email: "v@lumen.test",
    is_active: true,
    email_verified_at: null,
    created_at: "2026-01-01T00:00:00Z",
  } as Record<string, unknown> | null,
};
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({ ...authState, ready: true, token: "t" }),
}));

const baseSample: CourseListItem = {
  id: "c1",
  title: "FastAPI from Zero",
  slug: "fastapi-from-zero",
  overview: "Build a tiny API.",
  difficulty: "beginner",
  cover_url: null,
  status: "published",
  visibility: "private",
  moderation_state: null,
  is_featured: true,
  published_at: "2026-05-01T00:00:00Z",
  created_at: "2026-05-01T00:00:00Z",
  owner: { id: "u1", full_name: "Tareq", avatar_url: null, bio: null, role: "instructor" },
  subject: { id: "s1", title: "Programming", slug: "programming", total_courses: 0 },
  tags: [{ id: "t1", name: "Python", slug: "python" }],
  modules_count: 3,
  enrollments_count: 42,
  avg_rating: 4.5,
  origin: null,
  is_clone: false,
};

function renderCard(course: CourseListItem) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CourseCard course={course} />
    </QueryClientProvider>,
  );
}

describe("CourseCard", () => {
  it("renders the course title, owner, and stats", () => {
    renderCard(baseSample);
    expect(screen.getByText("FastAPI from Zero")).toBeInTheDocument();
    expect(screen.getByText("Tareq")).toBeInTheDocument();
    expect(screen.getByText("3 modules")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("4.5")).toBeInTheDocument();
    expect(screen.getByText("Featured")).toBeInTheDocument();
  });

  it("links to the slug", () => {
    renderCard(baseSample);
    const link = screen.getByRole("link", { name: /FastAPI from Zero/ });
    expect(link).toHaveAttribute("href", "/courses/fastapi-from-zero");
  });

  it("hides the Featured badge when is_featured is false", () => {
    renderCard({ ...baseSample, is_featured: false });
    expect(screen.queryByText("Featured")).not.toBeInTheDocument();
  });

  it("omits the rating tile when avg_rating is null", () => {
    renderCard({ ...baseSample, avg_rating: null });
    expect(screen.queryByText("4.5")).not.toBeInTheDocument();
  });

  it("renders the cover image when cover_url is provided", () => {
    renderCard({ ...baseSample, cover_url: "https://cdn.test/cover.jpg" });
    const img = document.querySelector('img[src="https://cdn.test/cover.jpg"]');
    expect(img).not.toBeNull();
  });

  it("renders a decorative glyph fallback when there is no cover image", () => {
    const { container } = renderCard(baseSample);
    // No <img> when cover_url is null
    expect(container.querySelector("img")).toBeNull();
    // The empty-cover area contains an SVG glyph — keyed to the scroll
    // motif from the lumen primitives. We assert there is *some* SVG
    // rather than pin a viewBox, so future glyph swaps don't break.
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("renders the difficulty + subject badges", () => {
    renderCard(baseSample);
    expect(screen.getByText("Programming")).toBeInTheDocument();
    expect(screen.getByText("beginner")).toBeInTheDocument();
  });
});

describe("CourseCard — clone CTA gating (S4.11)", () => {
  it("shows the clone CTA for a signed-in viewer on a publicly-listed course", () => {
    renderCard({ ...baseSample, visibility: "public" });
    expect(screen.getByRole("button", { name: en["clone.cta"] })).toBeInTheDocument();
  });

  it("hides the clone CTA on a private (not publicly listed) course", () => {
    renderCard({ ...baseSample, visibility: "private" });
    expect(screen.queryByRole("button", { name: en["clone.cta"] })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: en["clone.signInToClone"] })).not.toBeInTheDocument();
  });

  it("offers a sign-in affordance to an anonymous viewer on a public course", () => {
    authState.user = null;
    try {
      renderCard({ ...baseSample, visibility: "public" });
      expect(screen.queryByRole("button", { name: en["clone.cta"] })).not.toBeInTheDocument();
      const signin = screen.getByRole("link", { name: en["clone.signInToClone"] });
      expect(signin.getAttribute("href")).toContain(
        encodeURIComponent("/courses/fastapi-from-zero"),
      );
    } finally {
      authState.user = {
        id: "u9",
        full_name: "Viewer",
        avatar_url: null,
        bio: null,
        role: "user",
        email: "v@lumen.test",
        is_active: true,
        email_verified_at: null,
        created_at: "2026-01-01T00:00:00Z",
      };
    }
  });
});
