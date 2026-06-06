/**
 * Admin moderation page — actions + reports tab (S6.11 / FR-MOD-15).
 *
 * S2 shipped the read-only queue; S6 layers the approve/reject/delist/relist/
 * remove ACTIONS plus the reports tab and the report-resolve flow. These specs
 * pin the wired contract by spying on the `Admin` endpoint object and rendering
 * the real page under a QueryClientProvider (the established idiom — see
 * tests/byok-model-page.test.tsx and tests/studio-editor-lifecycle.test.tsx).
 *
 *  1. The pending queue renders a row with action buttons.
 *  2. Approve/reject/delist/relist call the matching `Admin` method.
 *  3. Remove requires a confirmation step + a reason before it fires.
 *  4. The reports tab lists reports with the sanitized note as inert text
 *     (no `dangerouslySetInnerHTML`), and resolve fires `Admin.resolveReport`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { en } from "@/lib/i18n/messages/en";
import * as endpoints from "@/lib/api/endpoints";
import type { CourseListItem, ReportOut } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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

import AdminModerationPage from "@/app/admin/moderation/page";

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AdminModerationPage />
    </QueryClientProvider>,
  );
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
  owner: { id: "o1", full_name: "Owner One", avatar_url: null, bio: null, role: "user" },
  subject: { id: "s1", title: "Prog", slug: "prog", total_courses: 0 },
  tags: [],
  modules_count: 1,
  enrollments_count: 0,
  avg_rating: null,
};

const REPORT: ReportOut = {
  id: "r1",
  course_id: "c1",
  reporter_id: "u9",
  reason: "spam",
  note: "&lt;script&gt;alert(1)&lt;/script&gt; please review",
  status: "open",
  created_at: "2026-08-02T00:00:00Z",
  resolved_at: null,
  resolved_by: null,
};

beforeEach(() => {
  vi.spyOn(endpoints.Admin, "moderationQueue").mockResolvedValue([PENDING]);
  vi.spyOn(endpoints.Admin, "reports").mockResolvedValue([REPORT]);
});

afterEach(() => vi.restoreAllMocks());

describe("AdminModerationPage actions (S6.11)", () => {
  it("renders the pending queue with action buttons", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("moderation-row")).toBeInTheDocument());
    // Inert title text (literal markup string, not parsed HTML).
    expect(screen.getByText("Pending course <b>raw</b>")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: en["adminModeration.approve"] }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: en["adminModeration.reject"] }),
    ).toBeInTheDocument();
  });

  it("approve fires Admin.approveCourse", async () => {
    const approve = vi
      .spyOn(endpoints.Admin, "approveCourse")
      .mockResolvedValue({ ...PENDING, moderation_state: "approved" });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("moderation-row")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: en["adminModeration.approve"] }));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("c1", expect.anything()));
  });

  it("reject fires Admin.rejectCourse", async () => {
    const reject = vi
      .spyOn(endpoints.Admin, "rejectCourse")
      .mockResolvedValue({ ...PENDING, moderation_state: "rejected" });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("moderation-row")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: en["adminModeration.reject"] }));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("c1", expect.anything()));
  });

  it("remove requires a confirmation dialog with a reason before firing", async () => {
    const remove = vi
      .spyOn(endpoints.Admin, "removeCourse")
      .mockResolvedValue({ ...PENDING, moderation_state: "delisted" });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("moderation-row")).toBeInTheDocument());

    // Clicking Remove opens a confirm dialog — it must NOT fire immediately.
    await userEvent.click(screen.getByRole("button", { name: en["adminModeration.remove"] }));
    expect(remove).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(en["adminModeration.confirmRemoveTitle"]),
    ).toBeInTheDocument();

    // The confirm button is disabled until a reason is selected.
    const confirm = within(dialog).getByTestId("confirm-remove");
    expect(confirm).toBeDisabled();
  });

  it("reports tab lists a report with the note rendered as inert text", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId("moderation-row")).toBeInTheDocument());
    await userEvent.click(
      screen.getByRole("tab", { name: en["adminModeration.tab.reports"] }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("report-row")).toBeInTheDocument(),
    );
    // The already-sanitized note string is shown verbatim (no script element).
    expect(
      screen.getByText(/please review/),
    ).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(
      screen.getByRole("button", { name: en["adminModeration.reports.resolve"] }),
    ).toBeInTheDocument();
  });

  it("resolving a report fires Admin.resolveReport", async () => {
    const resolve = vi
      .spyOn(endpoints.Admin, "resolveReport")
      .mockResolvedValue({ ...REPORT, status: "dismissed" });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("moderation-row")).toBeInTheDocument());
    await userEvent.click(
      screen.getByRole("tab", { name: en["adminModeration.tab.reports"] }),
    );
    await waitFor(() => expect(screen.getByTestId("report-row")).toBeInTheDocument());
    await userEvent.click(
      screen.getByRole("button", { name: en["adminModeration.reports.resolve"] }),
    );
    const dialog = await screen.findByRole("dialog");
    // Default action is dismiss; confirm it.
    await userEvent.click(within(dialog).getByTestId("confirm-resolve"));
    await waitFor(() =>
      expect(resolve).toHaveBeenCalledWith(
        "r1",
        expect.objectContaining({ action: "dismiss" }),
      ),
    );
  });
});
