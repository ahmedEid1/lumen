/**
 * Admin moderation queue page (S2.12).
 *
 * S2 ships the read surface (the queue). Mounts the page as an admin with a
 * stubbed moderation-queue response and asserts the pending course renders as a
 * row (title as inert text + visibility/moderation badges); an empty queue
 * renders the empty-state.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminModerationPage from "@/app/admin/moderation/page";
import * as endpoints from "@/lib/api/endpoints";
import type { CourseListItem } from "@/lib/api/types";

vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: { id: "a1", email: "admin@lumen.test", full_name: "Admin", role: "admin" },
    token: "tk",
    ready: true,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const PENDING: CourseListItem = {
  id: "c1",
  title: "Pending course <b>raw</b>",
  slug: "pending-course",
  overview: "x",
  difficulty: "beginner",
  cover_url: null,
  status: "published",
  visibility: "public",
  moderation_state: "pending_review",
  is_featured: false,
  published_at: null,
  created_at: "2026-08-01T00:00:00Z",
  owner: { id: "o1", full_name: "Owner One", avatar_url: null, bio: null, role: "instructor" },
  subject: { id: "s1", title: "Prog", slug: "prog", total_courses: 0 },
  tags: [],
  modules_count: 1,
  enrollments_count: 0,
  avg_rating: null,
};

afterEach(() => vi.restoreAllMocks());

describe("AdminModerationPage", () => {
  it("renders a pending course as a queue row with inert title + badges", async () => {
    vi.spyOn(endpoints.Courses, "moderationQueue").mockResolvedValue([PENDING]);
    renderWithClient(<AdminModerationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("moderation-row")).toBeInTheDocument();
    });
    // Title rendered as inert text (the literal markup string appears, not <b>).
    expect(screen.getByText("Pending course <b>raw</b>")).toBeInTheDocument();
    expect(screen.getByText("Owner One")).toBeInTheDocument();
    expect(screen.getByText("pending_review")).toBeInTheDocument();
  });

  it("renders the empty-state when the queue is empty", async () => {
    vi.spyOn(endpoints.Courses, "moderationQueue").mockResolvedValue([]);
    renderWithClient(<AdminModerationPage />);
    await waitFor(() => {
      expect(screen.getByTestId("moderation-empty")).toBeInTheDocument();
    });
  });
});
