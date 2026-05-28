import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionsCard } from "@/components/shared/sessions-card";
import * as apiClient from "@/lib/api/client";

// Suppress sonner's toast in test output
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SESSIONS = [
  {
    id: "s_a",
    issued_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    revoked_at: null,
    user_agent: "Chrome 120",
    ip_address: "10.0.0.1",
  },
  {
    id: "s_b",
    issued_at: new Date(Date.now() - 3_600_000).toISOString(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    revoked_at: null,
    user_agent: "Safari 17",
    ip_address: "10.0.0.2",
  },
];

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("SessionsCard", () => {
  let apiSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    apiSpy = vi.spyOn(apiClient, "api");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders one row per session and a Sign out everywhere button", async () => {
    apiSpy.mockResolvedValueOnce(SESSIONS as never);
    renderWithClient(<SessionsCard />);
    expect(await screen.findByText("Chrome 120")).toBeInTheDocument();
    expect(screen.getByText("Safari 17")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out everywhere/i })).toBeInTheDocument();
  });

  it("revokes a single session via the per-row trash button", async () => {
    apiSpy.mockResolvedValueOnce(SESSIONS as never); // initial list
    apiSpy.mockResolvedValueOnce({ ok: true } as never); // DELETE one
    apiSpy.mockResolvedValueOnce(
      [
        { ...SESSIONS[0], revoked_at: new Date().toISOString() },
        SESSIONS[1],
      ] as never,
    ); // refetch

    renderWithClient(<SessionsCard />);
    await screen.findByText("Chrome 120");

    const revokeButtons = screen.getAllByLabelText(/revoke session/i);
    expect(revokeButtons).toHaveLength(2);

    await userEvent.setup().click(revokeButtons[0]);

    await waitFor(() => {
      expect(apiSpy).toHaveBeenCalledWith(
        expect.stringMatching(/\/api\/v1\/users\/me\/sessions\/s_a$/),
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });

  it("revokes all sessions via the header button", async () => {
    apiSpy.mockResolvedValueOnce(SESSIONS as never);
    apiSpy.mockResolvedValueOnce({ ok: true } as never);
    apiSpy.mockResolvedValueOnce([] as never);

    renderWithClient(<SessionsCard />);
    await screen.findByText("Chrome 120");

    await userEvent.setup().click(screen.getByRole("button", { name: /sign out everywhere/i }));

    await waitFor(() => {
      expect(apiSpy).toHaveBeenCalledWith(
        "/api/v1/users/me/sessions",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });

  it("shows an empty-state when no sessions are returned", async () => {
    apiSpy.mockResolvedValueOnce([] as never);
    renderWithClient(<SessionsCard />);
    expect(await screen.findByText(/no sessions on record/i)).toBeInTheDocument();
  });

  it("hides revoked sessions behind a 'show history' toggle", async () => {
    const REVOKED = {
      id: "s_old",
      issued_at: new Date(Date.now() - 7_200_000).toISOString(),
      expires_at: new Date(Date.now() + 86_400_000).toISOString(),
      revoked_at: new Date(Date.now() - 3_600_000).toISOString(),
      user_agent: "HeadlessChrome QA",
      ip_address: "10.9.9.9",
    };
    apiSpy.mockResolvedValueOnce([SESSIONS[0], REVOKED] as never);
    renderWithClient(<SessionsCard />);
    // Active session visible; revoked one hidden until the toggle is used.
    expect(await screen.findByText("Chrome 120")).toBeInTheDocument();
    expect(screen.queryByText("HeadlessChrome QA")).toBeNull();

    await userEvent.setup().click(screen.getByRole("button", { name: /show 1 revoked/i }));
    expect(screen.getByText("HeadlessChrome QA")).toBeInTheDocument();
  });
});
