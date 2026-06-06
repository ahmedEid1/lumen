/**
 * User-side course report affordance (W11 · FR-MOD-11 / S6.3).
 *
 * Pins the contract on the public course surface:
 *
 *  1. The trigger renders only for a signed-in viewer who is NOT the owner;
 *     hidden for anonymous viewers and for the owner.
 *  2. Submitting calls `Courses.report` with the chosen reason (+ optional note)
 *     and, on 201, toasts success and flips the trigger to an inert "Reported".
 *  3. The backend error codes map to the localized toasts:
 *       - 422 `report.own_course`        → report.ownCourse
 *       - 429 `course.report_rate_limited` → report.rateLimited
 *
 * Mirrors tests/clone-button.test.tsx: real `en` copy via the global i18n mock,
 * `Courses` methods spied, sonner stubbed.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as endpoints from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { en } from "@/lib/i18n/messages/en";
import type { CourseDetail, UserPublic } from "@/lib/api/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "sonner";
import { ReportButton } from "@/components/course/report-button";

const OWNER: UserPublic = {
  id: "owner1",
  full_name: "Course Owner",
  avatar_url: null,
  bio: null,
  role: "instructor",
};

function makeCourse(): Pick<CourseDetail, "id" | "owner"> {
  return { id: "c1", owner: OWNER };
}

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client };
}

afterEach(() => vi.restoreAllMocks());

describe("ReportButton — render gating", () => {
  it("hides the trigger for anonymous viewers", () => {
    renderWithClient(<ReportButton course={makeCourse()} user={null} />);
    expect(screen.queryByRole("button", { name: en["report.cta"] })).not.toBeInTheDocument();
  });

  it("hides the trigger for the course owner", () => {
    renderWithClient(<ReportButton course={makeCourse()} user={{ id: "owner1" }} />);
    expect(screen.queryByRole("button", { name: en["report.cta"] })).not.toBeInTheDocument();
  });

  it("renders the trigger for a signed-in non-owner viewer", () => {
    renderWithClient(<ReportButton course={makeCourse()} user={{ id: "viewer9" }} />);
    expect(screen.getByRole("button", { name: en["report.cta"] })).toBeInTheDocument();
  });
});

describe("ReportButton — submit flow", () => {
  it("submits the chosen reason + note and flips to an inert 'Reported' on success", async () => {
    const reportSpy = vi
      .spyOn(endpoints.Courses, "report")
      .mockResolvedValue({ ok: true } as { ok: true });
    renderWithClient(<ReportButton course={makeCourse()} user={{ id: "viewer9" }} />);

    await userEvent.click(screen.getByRole("button", { name: en["report.cta"] }));

    // Open the reason Select and pick "Spam".
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: en["reason.spam"] }));

    // Optional details.
    await userEvent.type(screen.getByLabelText(en["report.detailsLabel"]), "looks like spam");

    await userEvent.click(screen.getByRole("button", { name: en["report.submit"] }));

    await waitFor(() =>
      expect(reportSpy).toHaveBeenCalledWith("c1", { reason: "spam", note: "looks like spam" }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(en["report.success"]));

    // The trigger is now inert "Reported" for the session.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: en["report.reported"] })).toBeDisabled(),
    );
    expect(screen.queryByRole("button", { name: en["report.cta"] })).not.toBeInTheDocument();
  });

  it("sends a null note when details are left empty", async () => {
    const reportSpy = vi
      .spyOn(endpoints.Courses, "report")
      .mockResolvedValue({ ok: true } as { ok: true });
    renderWithClient(<ReportButton course={makeCourse()} user={{ id: "viewer9" }} />);

    await userEvent.click(screen.getByRole("button", { name: en["report.cta"] }));
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: en["reason.copyright"] }));
    await userEvent.click(screen.getByRole("button", { name: en["report.submit"] }));

    await waitFor(() =>
      expect(reportSpy).toHaveBeenCalledWith("c1", { reason: "copyright", note: null }),
    );
  });

  it("maps the 422 own-course code to the localized toast and stays reportable", async () => {
    vi.spyOn(endpoints.Courses, "report").mockRejectedValue(
      new ApiError({ status: 422, message: "own", code: "report.own_course" }),
    );
    renderWithClient(<ReportButton course={makeCourse()} user={{ id: "viewer9" }} />);

    await userEvent.click(screen.getByRole("button", { name: en["report.cta"] }));
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: en["reason.abuse"] }));
    await userEvent.click(screen.getByRole("button", { name: en["report.submit"] }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(en["report.ownCourse"]));
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("maps the 429 rate-limited code to the localized toast", async () => {
    vi.spyOn(endpoints.Courses, "report").mockRejectedValue(
      new ApiError({ status: 429, message: "slow", code: "course.report_rate_limited" }),
    );
    renderWithClient(<ReportButton course={makeCourse()} user={{ id: "viewer9" }} />);

    await userEvent.click(screen.getByRole("button", { name: en["report.cta"] }));
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: en["reason.other"] }));
    await userEvent.click(screen.getByRole("button", { name: en["report.submit"] }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(en["report.rateLimited"]));
  });
});
