/**
 * Studio editor two-control rewire (Gate-C major, S2.11/S2.12 · ADR-0026).
 *
 * The editor at /studio/[id] used to publish via PATCH {status} — a 422 since
 * S2 (FR-VIS-08). These tests pin the rewired contract:
 *
 *  1. The Publish button hits POST /publish (Courses.publish), NOT PATCH.
 *  2. Archive hits POST /archive (Courses.archive).
 *  3. The Share control renders for a published course and fires POST /share.
 *  4. The moderation badge renders the pending_review copy for a shared course.
 *
 * Mocks `Courses` (spy on the lifecycle/share methods, stub the read methods)
 * and renders the real page under a QueryClientProvider, mirroring
 * tests/admin-moderation-page.test.tsx. i18n is mocked to resolve real `en`
 * copy so the badge assertion checks the visible string.
 */

import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as endpoints from "@/lib/api/endpoints";
import { en } from "@/lib/i18n/messages/en";
import type { CourseDetail } from "@/lib/api/types";

// i18n (useT/useTN) + next/navigation are mocked globally in tests/setup.ts —
// the i18n mock already resolves real `en` copy, so visible-text assertions
// (the moderation badge, the button labels) check the rendered string.

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// The page calls `use(params)`, which suspends until the params promise
// resolves. Render inside an async `act` so the suspense + the initial
// course/analytics queries flush before assertions run.
async function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Suspense fallback={null}>{ui}</Suspense>
      </QueryClientProvider>,
    );
  });
}

function makeCourse(over: Partial<CourseDetail> = {}): CourseDetail {
  return {
    id: "c1",
    title: "FastAPI in 90 Minutes",
    slug: "fastapi-in-90-minutes",
    overview: "An overview.",
    difficulty: "beginner",
    cover_url: null,
    status: "draft",
    visibility: "private",
    moderation_state: "none",
    is_featured: false,
    published_at: null,
    created_at: "2026-08-01T00:00:00Z",
    owner: { id: "o1", full_name: "Owner", avatar_url: null, bio: null, role: "instructor" },
    subject: { id: "s1", title: "Prog", slug: "prog", total_courses: 0 },
    tags: [],
    modules_count: 0,
    enrollments_count: 0,
    avg_rating: null,
    modules: [],
    is_enrolled: false,
    progress_pct: 0,
    is_publicly_listed: false,
    can_publish_public: true,
    learning_outcomes: [],
    ...over,
  };
}

function stubReads(course: CourseDetail) {
  vi.spyOn(endpoints.Courses, "get").mockResolvedValue(course);
  vi.spyOn(endpoints.Courses, "analytics").mockResolvedValue({
    course_id: "c1",
    enrollments: 0,
    completions: 0,
    completion_rate: 0,
    avg_rating: null,
    rating_count: 0,
    avg_progress_pct: 0,
    enrollments_last_7d: 0,
    enrollments_last_30d: 0,
  });
  vi.spyOn(endpoints.Courses, "cohort").mockResolvedValue([]);
}

const params = () => Promise.resolve({ id: "c1" });

afterEach(() => vi.restoreAllMocks());

// Import after mocks are registered.
import StudioCoursePage from "@/app/studio/[id]/page";

describe("Studio editor two-control rewire", () => {
  it("Publish button calls POST /publish (Courses.publish), not PATCH", async () => {
    stubReads(makeCourse({ status: "draft" }));
    const patch = vi.spyOn(endpoints.Courses, "patch");
    const publish = vi
      .spyOn(endpoints.Courses, "publish")
      .mockResolvedValue(makeCourse({ status: "published" }));

    await renderWithClient(<StudioCoursePage params={params()} />);
    const btn = await screen.findByRole("button", { name: en["studioEdit.publish"] });
    await userEvent.click(btn);

    await waitFor(() => expect(publish).toHaveBeenCalledWith("c1"));
    expect(patch).not.toHaveBeenCalled();
  });

  it("Archive button calls POST /archive (Courses.archive)", async () => {
    stubReads(makeCourse({ status: "draft" }));
    const archive = vi
      .spyOn(endpoints.Courses, "archive")
      .mockResolvedValue(makeCourse({ status: "archived" }));

    await renderWithClient(<StudioCoursePage params={params()} />);
    const btn = await screen.findByRole("button", { name: en["studioEdit.archive"] });
    await userEvent.click(btn);

    await waitFor(() => expect(archive).toHaveBeenCalledWith("c1"));
  });

  it("renders the Share control for a published course and fires POST /share", async () => {
    stubReads(makeCourse({ status: "published", visibility: "private" }));
    const share = vi
      .spyOn(endpoints.Courses, "share")
      .mockResolvedValue(makeCourse({ status: "published", visibility: "public" }));

    await renderWithClient(<StudioCoursePage params={params()} />);
    const btn = await screen.findByRole("button", { name: en["studio.share.shareCta"] });
    expect(btn).toBeEnabled();
    await userEvent.click(btn);

    await waitFor(() => expect(share).toHaveBeenCalledWith("c1"));
  });

  it("disables the Share control until the course is published (FR-VIS-23)", async () => {
    stubReads(makeCourse({ status: "draft" }));
    await renderWithClient(<StudioCoursePage params={params()} />);
    const btn = await screen.findByRole("button", { name: en["studio.share.shareCta"] });
    expect(btn).toBeDisabled();
  });

  it("renders the moderation badge with pending_review copy for a shared course", async () => {
    stubReads(
      makeCourse({ status: "published", visibility: "public", moderation_state: "pending_review" }),
    );
    await renderWithClient(<StudioCoursePage params={params()} />);
    await waitFor(() => {
      expect(screen.getByTestId("moderation-state")).toHaveTextContent(
        en["studio.share.pendingReview"],
      );
    });
  });
});
