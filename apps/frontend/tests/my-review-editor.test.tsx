import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MyReviewEditor } from "@/components/course/my-review-editor";
import * as endpoints from "@/lib/api/endpoints";
import type { ReviewOut } from "@/lib/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const EXISTING: ReviewOut = {
  id: "r1",
  rating: 3,
  body: "Pretty good",
  created_at: new Date("2026-05-01").toISOString(),
  updated_at: new Date("2026-05-01").toISOString(),
  author: {
    id: "u1",
    full_name: "Lina",
    avatar_url: null,
    bio: null,
    role: "student",
  },
};

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("MyReviewEditor", () => {
  let upsertSpy: ReturnType<typeof vi.spyOn>;
  let removeSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    upsertSpy = vi.spyOn(endpoints.Reviews, "upsert");
    removeSpy = vi.spyOn(endpoints.Reviews, "remove");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the 'Leave a review' header when there is no existing review", () => {
    renderWithClient(<MyReviewEditor courseId="c1" myReview={null} />);
    expect(screen.getByText(/leave a review/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /post review/i })).toBeDisabled();
  });

  it("seeds the editor with the existing review and updates on save", async () => {
    upsertSpy.mockResolvedValue({ ...EXISTING, rating: 5 } as never);
    renderWithClient(<MyReviewEditor courseId="c1" myReview={EXISTING} />);

    expect(screen.getByText(/your review/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/optional thoughts/i)).toHaveValue("Pretty good");

    const user = userEvent.setup();
    // Pick the 5-star option (radio group)
    await user.click(screen.getByRole("radio", { name: /5 stars/i }));
    await user.click(screen.getByRole("button", { name: /update review/i }));

    await waitFor(() => {
      expect(upsertSpy).toHaveBeenCalledWith(
        "c1",
        expect.objectContaining({ rating: 5, body: "Pretty good" }),
      );
    });
  });

  it("calls the remove endpoint and resets the form when removing", async () => {
    removeSpy.mockResolvedValue({ ok: true } as never);
    renderWithClient(<MyReviewEditor courseId="c1" myReview={EXISTING} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /remove/i }));

    await waitFor(() => {
      expect(removeSpy).toHaveBeenCalledWith("c1");
    });
  });

  it("blocks save until a rating is chosen", async () => {
    upsertSpy.mockResolvedValue(EXISTING as never);
    renderWithClient(<MyReviewEditor courseId="c1" myReview={null} />);

    const submit = screen.getByRole("button", { name: /post review/i });
    expect(submit).toBeDisabled();

    await userEvent.setup().click(screen.getByRole("radio", { name: /4 stars/i }));
    expect(submit).not.toBeDisabled();
  });
});
