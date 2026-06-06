/**
 * Clone CTA + origin attribution (S4.11 · ADR-0028).
 *
 * Pins the clone-affordance contract on the public surfaces:
 *
 *  1. <CloneButton> renders only for a viewer who can clone a
 *     publicly-listed course; hidden for anonymous / not-listed.
 *  2. Anonymous click routes to /login with a `next` return path
 *     (handled by the card/sidebar wrappers).
 *  3. A 201 success calls Courses.clone, routes to the new course's
 *     editor /studio/{newId} (NOT the AI trace surface /studio/draft/{id},
 *     which is empty for a clone — W11 F3), and invalidates myCourses +
 *     enrollments.
 *  4. 429 / 409 / 413 surface the matching localized error toast.
 *  5. <OriginAttribution> renders a "View original" link when the
 *     origin is available, plain "no longer available" text when not,
 *     and only ever the immediate parent (root origin is never shown).
 *
 * Mirrors tests/studio-editor-lifecycle.test.tsx: real `en` copy via
 * the global i18n mock, `Courses` methods spied, sonner stubbed. The
 * shared router-push spy is hoisted so the navigation assertion can
 * read it (the global next/navigation mock hands back a throwaway
 * push per call, so we install a local mock here).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as endpoints from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { en } from "@/lib/i18n/messages/en";
import type { CourseListItem, CourseOrigin } from "@/lib/api/types";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
  useParams: () => ({}),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "sonner";
import { CloneButton } from "@/components/course/clone-button";
import { OriginAttribution } from "@/components/course/origin-attribution";

function makeListItem(over: Partial<CourseListItem> = {}): CourseListItem {
  return {
    id: "src1",
    title: "FastAPI in 90 Minutes",
    slug: "fastapi-in-90-minutes",
    overview: "An overview.",
    difficulty: "beginner",
    cover_url: null,
    status: "published",
    visibility: "public",
    moderation_state: null,
    is_featured: false,
    published_at: "2026-08-01T00:00:00Z",
    created_at: "2026-08-01T00:00:00Z",
    owner: { id: "o1", full_name: "Owner", avatar_url: null, bio: null, role: "instructor" },
    subject: { id: "s1", title: "Prog", slug: "prog", total_courses: 0 },
    tags: [],
    modules_count: 3,
    enrollments_count: 0,
    avg_rating: null,
    origin: null,
    is_clone: false,
    ...over,
  };
}

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client };
}

afterEach(() => {
  vi.restoreAllMocks();
  pushMock.mockReset();
});

describe("CloneButton — render gating", () => {
  it("renders the CTA for a viewer who can clone a publicly-listed course", () => {
    renderWithClient(<CloneButton course={makeListItem()} canClone />);
    expect(screen.getByRole("button", { name: en["clone.cta"] })).toBeInTheDocument();
  });

  it("hides the CTA when the viewer cannot clone (anonymous)", () => {
    renderWithClient(<CloneButton course={makeListItem()} canClone={false} />);
    expect(screen.queryByRole("button", { name: en["clone.cta"] })).not.toBeInTheDocument();
    // Anonymous instead gets a sign-in affordance that returns to the course.
    const signin = screen.getByRole("link", { name: en["clone.signInToClone"] });
    expect(signin).toHaveAttribute("href", expect.stringContaining("/login?next="));
    expect(signin.getAttribute("href")).toContain(
      encodeURIComponent("/courses/fastapi-in-90-minutes"),
    );
  });

  it("hides the CTA entirely when the course is not publicly listed", () => {
    renderWithClient(<CloneButton course={makeListItem({ visibility: "private" })} canClone />);
    expect(screen.queryByRole("button", { name: en["clone.cta"] })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: en["clone.signInToClone"] })).not.toBeInTheDocument();
  });
});

describe("CloneButton — clone mutation", () => {
  it("on 201 success routes to /studio/{newId} and invalidates myCourses + enrollments", async () => {
    vi.spyOn(endpoints.Courses, "clone").mockResolvedValue(
      makeListItem({
        id: "new9",
        slug: "fastapi-in-90-minutes-copy",
        visibility: "private",
        status: "draft",
      }),
    );
    const { client } = renderWithClient(<CloneButton course={makeListItem()} canClone />);
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await userEvent.click(screen.getByRole("button", { name: en["clone.cta"] }));

    await waitFor(() => expect(endpoints.Courses.clone).toHaveBeenCalledWith({ key: "src1" }));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/studio/new9"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me", "my-courses"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["me", "enrollments"] });
  });

  it("surfaces the rate-limited toast on 429", async () => {
    vi.spyOn(endpoints.Courses, "clone").mockRejectedValue(
      new ApiError({ status: 429, message: "slow down", code: "clone.rate_limited" }),
    );
    renderWithClient(<CloneButton course={makeListItem()} canClone />);
    await userEvent.click(screen.getByRole("button", { name: en["clone.cta"] }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(en["clone.error.rateLimited"]));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("surfaces the course-limit toast on 409", async () => {
    vi.spyOn(endpoints.Courses, "clone").mockRejectedValue(
      new ApiError({ status: 409, message: "cap", code: "clone.course_limit" }),
    );
    renderWithClient(<CloneButton course={makeListItem()} canClone />);
    await userEvent.click(screen.getByRole("button", { name: en["clone.cta"] }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(en["clone.error.courseLimit"]));
  });

  it("surfaces the too-large toast on 413", async () => {
    vi.spyOn(endpoints.Courses, "clone").mockRejectedValue(
      new ApiError({ status: 413, message: "too big", code: "clone.source_too_large" }),
    );
    renderWithClient(<CloneButton course={makeListItem()} canClone />);
    await userEvent.click(screen.getByRole("button", { name: en["clone.cta"] }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(en["clone.error.tooLarge"]));
  });

  it("falls back to the generic toast on an unmapped error", async () => {
    vi.spyOn(endpoints.Courses, "clone").mockRejectedValue(
      new ApiError({ status: 500, message: "boom", code: "internal" }),
    );
    renderWithClient(<CloneButton course={makeListItem()} canClone />);
    await userEvent.click(screen.getByRole("button", { name: en["clone.cta"] }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(en["clone.error.generic"]));
  });
});

describe("OriginAttribution", () => {
  function makeOrigin(over: Partial<CourseOrigin> = {}): CourseOrigin {
    return {
      origin_course_id: "src1",
      origin_title: "FastAPI in 90 Minutes",
      origin_owner_name: "Original Author",
      origin_owner_id: "o1",
      cloned_at: "2026-08-02T00:00:00Z",
      origin_available: true,
      ...over,
    };
  }

  it("renders a 'View original' link when the origin is available", () => {
    render(<OriginAttribution origin={makeOrigin()} />);
    const link = screen.getByRole("link", { name: en["clone.viewSource"] });
    expect(link).toHaveAttribute("href", "/courses/src1");
    // The structured "Based on …" line is present, interpolated.
    expect(screen.getByText(/FastAPI in 90 Minutes/)).toBeInTheDocument();
    expect(screen.getByText(/Original Author/)).toBeInTheDocument();
  });

  it("renders plain 'no longer available' text and no link when origin is gone", () => {
    render(<OriginAttribution origin={makeOrigin({ origin_available: false })} />);
    expect(screen.queryByRole("link", { name: en["clone.viewSource"] })).not.toBeInTheDocument();
    expect(screen.getByText(en["clone.basedOnUnavailable"])).toBeInTheDocument();
  });

  it("resolves the deleted-user label when the owner is tombstoned but origin is available", () => {
    // Backend returns the i18n KEY "common.deletedUser" as the owner name when
    // the origin owner is tombstoned/purged (DR-19). The render site must run it
    // through t() (Gate-B B2) — never interpolate "by common.deletedUser".
    render(
      <OriginAttribution origin={makeOrigin({ origin_owner_name: "common.deletedUser" })} />,
    );
    // The link still renders (origin_available stays true) ...
    expect(screen.getByRole("link", { name: en["clone.viewSource"] })).toBeInTheDocument();
    // ... and the localized label is shown, not the raw key.
    expect(
      screen.getByText(
        en["clone.basedOn"]
          .replace("{title}", "FastAPI in 90 Minutes")
          .replace("{author}", en["common.deletedUser"]),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/common\.deletedUser/)).not.toBeInTheDocument();
  });

  it("renders nothing when there is no origin", () => {
    const { container } = render(<OriginAttribution origin={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("never exposes an editable input (attribution is read-only, FR-CLONE-10)", () => {
    render(<OriginAttribution origin={makeOrigin()} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
