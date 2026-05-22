/**
 * Mastery dashboard page (Phase E7).
 *
 * Mounts the page with a stubbed ``Me.mastery()`` returning one
 * weak spot (a failed-quiz lesson with an overdue card) and one
 * enrolled course with mixed completion / mastery percentages.
 * Asserts:
 *   - the weak-spot row shows the lesson title, the course eyebrow,
 *     a pill per signal carrying the numeric detail, and a "Review
 *     now" CTA pointing at the FSRS surface (because the spot has
 *     a review_card_id);
 *   - the per-course row renders both progress bars labelled
 *     "Completion" and "Mastery" with the percentages alongside.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MasteryPage from "@/app/dashboard/mastery/page";
import * as endpoints from "@/lib/api/endpoints";
import type { MasteryResponse } from "@/lib/api/endpoints";

// The mastery page reads ``useAuth`` to gate-on auth + thread the
// token into the API call. The page bails to /login when there's no
// user, so we stub a ready user here.
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: {
      id: "u1",
      email: "learner@lumen.test",
      full_name: "Test Learner",
      role: "student",
      avatar_url: null,
      is_admin: false,
    },
    token: "tk_test",
    ready: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const FIXTURE: MasteryResponse = {
  weak_spots: [
    {
      lesson: {
        id: "l1",
        title: "Big-O analysis",
        course_id: "c1",
        course_slug: "algorithms",
        course_title: "Algorithms",
      },
      signals: ["quiz_failed", "card_overdue"],
      signal_details: {
        quiz_score: "40",
        overdue_days: "3",
      },
      review_card_id: "rc_xyz",
    },
  ],
  courses: [
    {
      course_id: "c1",
      slug: "algorithms",
      title: "Algorithms",
      mastery_pct: 67,
      completion_pct: 50,
    },
  ],
};

describe("MasteryPage", () => {
  let masterySpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    masterySpy = vi
      .spyOn(endpoints.Me, "mastery")
      .mockResolvedValue(FIXTURE as never);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders weak-spot signals and the per-course progress bars", async () => {
    renderWithClient(<MasteryPage />);

    // API should be called with the bearer token.
    await waitFor(() => {
      expect(masterySpy).toHaveBeenCalledWith("tk_test");
    });

    // The lesson title appears in the weak-spots list.
    expect(
      await screen.findByText("Big-O analysis"),
    ).toBeInTheDocument();
    // Course eyebrow.
    expect(screen.getAllByText("Algorithms").length).toBeGreaterThanOrEqual(1);

    // Signal pills carry the numeric details inline.
    expect(screen.getByText(/quiz: 40% \(failed\)/i)).toBeInTheDocument();
    expect(screen.getByText(/due 3 days/i)).toBeInTheDocument();

    // Because the weak spot has a review_card_id, the CTA points at
    // the FSRS review surface (not the lesson player).
    const reviewLink = screen.getByRole("link", { name: /review now/i });
    expect(reviewLink).toHaveAttribute("href", "/dashboard/reviews");

    // The per-course row renders BOTH progress bars (completion +
    // mastery) with the percentages alongside.
    const courseSection = screen
      .getByRole("heading", { name: /mastery per course/i })
      .closest("section");
    expect(courseSection).not.toBeNull();
    const courseScope = within(courseSection as HTMLElement);
    // Two labelled bars + their percentages.
    expect(courseScope.getByText(/completion/i)).toBeInTheDocument();
    // The "Mastery" label appears twice (one per bar), so we scope
    // to inside the course section to disambiguate from the page
    // header.
    expect(courseScope.getAllByText(/mastery/i).length).toBeGreaterThanOrEqual(1);
    expect(courseScope.getByText("50%")).toBeInTheDocument();
    expect(courseScope.getByText("67%")).toBeInTheDocument();
  });
});
