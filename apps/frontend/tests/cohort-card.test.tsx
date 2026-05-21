import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CohortCard } from "@/components/course/cohort-card";
import * as endpoints from "@/lib/api/endpoints";

const NOW = new Date().toISOString();

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("CohortCard", () => {
  let cohortSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    cohortSpy = vi.spyOn(endpoints.Courses, "cohort");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the empty state when nobody is enrolled", async () => {
    cohortSpy.mockResolvedValue([] as never);
    renderWithClient(<CohortCard courseId="c1" />);
    expect(await screen.findByText(/no enrolments yet/i)).toBeInTheDocument();
  });

  it("renders one row per learner with status badges and progress", async () => {
    cohortSpy.mockResolvedValue([
      {
        user_id: "u1",
        full_name: "Lina",
        avatar_url: null,
        enrolled_at: NOW,
        completed_at: NOW,
        progress_pct: 100,
        certificate_id: "cert_x",
      },
      {
        user_id: "u2",
        full_name: "Sam",
        avatar_url: null,
        enrolled_at: NOW,
        completed_at: null,
        progress_pct: 45,
        certificate_id: null,
      },
      {
        user_id: "u3",
        full_name: "Jess",
        avatar_url: null,
        enrolled_at: NOW,
        completed_at: null,
        progress_pct: 0,
        certificate_id: null,
      },
    ] as never);

    renderWithClient(<CohortCard courseId="c1" />);
    expect(await screen.findByText("Lina")).toBeInTheDocument();
    expect(screen.getByText("Sam")).toBeInTheDocument();
    expect(screen.getByText("Jess")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("in progress")).toBeInTheDocument();
    expect(screen.getByText("not started")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByText("45%")).toBeInTheDocument();
  });

  it("renders the error message when the request fails", async () => {
    cohortSpy.mockRejectedValue(new Error("forbidden") as never);
    renderWithClient(<CohortCard courseId="c1" />);
    expect(await screen.findByText(/forbidden/i)).toBeInTheDocument();
  });
});
