import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NotificationsBell } from "@/components/shared/notifications-bell";
import * as apiClient from "@/lib/api/client";

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const NOTIFS = [
  {
    id: "n1",
    kind: "enrolled",
    title: "Welcome to FastAPI",
    body: "Enjoy the course.",
    data: {},
    created_at: new Date().toISOString(),
    read_at: null,
  },
  {
    id: "n2",
    kind: "review_received",
    title: "New review",
    body: "5 stars",
    data: {},
    created_at: new Date().toISOString(),
    read_at: new Date().toISOString(),
  },
];

describe("NotificationsBell", () => {
  let apiSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    apiSpy = vi.spyOn(apiClient, "api");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the unread count on the badge", async () => {
    apiSpy.mockResolvedValueOnce(NOTIFS as never);
    renderWithClient(<NotificationsBell />);
    const btn = await screen.findByRole("button", { name: /1 unread/i });
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent("1");
  });

  it("opens the dropdown and marks an unread notification as read on click", async () => {
    apiSpy.mockResolvedValueOnce(NOTIFS as never); // initial list
    apiSpy.mockResolvedValueOnce({ ok: true } as never); // POST read
    apiSpy.mockResolvedValueOnce(
      NOTIFS.map((n) => ({ ...n, read_at: new Date().toISOString() })) as never,
    );

    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    const btn = await screen.findByRole("button", { name: /notifications/i });
    await user.click(btn);

    expect(await screen.findByText("Welcome to FastAPI")).toBeInTheDocument();

    // Click the unread notification to mark it as read
    await user.click(screen.getByText("Welcome to FastAPI"));

    await waitFor(() => {
      expect(apiSpy).toHaveBeenCalledWith(
        "/api/v1/me/notifications/n1/read",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("renders the empty state when there are no notifications", async () => {
    apiSpy.mockResolvedValueOnce([] as never);
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /notifications/i }));
    expect(screen.getByText(/nothing here yet/i)).toBeInTheDocument();
  });

  it("shows Mark all read when there is an unread count and calls the endpoint", async () => {
    apiSpy.mockResolvedValueOnce(NOTIFS as never); // initial list
    apiSpy.mockResolvedValueOnce({ ok: true, marked_read: 1 } as never); // read-all
    apiSpy.mockResolvedValueOnce(
      NOTIFS.map((n) => ({ ...n, read_at: new Date().toISOString() })) as never,
    );

    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /notifications/i }));

    const markAll = await screen.findByRole("button", { name: /mark all read/i });
    await user.click(markAll);

    await waitFor(() => {
      expect(apiSpy).toHaveBeenCalledWith(
        "/api/v1/me/notifications/read-all",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  it("hides Mark all read when nothing is unread", async () => {
    apiSpy.mockResolvedValueOnce(
      NOTIFS.map((n) => ({ ...n, read_at: new Date().toISOString() })) as never,
    );
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /notifications/i }));
    expect(screen.queryByRole("button", { name: /mark all read/i })).toBeNull();
  });

  it("surfaces the 50-item cap note only when the list is full", async () => {
    // Full page (50) → the bell can't reach older notifications, so it says so.
    const full = Array.from({ length: 50 }, (_, i) => ({
      ...NOTIFS[1],
      id: `c${i}`,
      title: `Notice ${i}`,
    }));
    apiSpy.mockResolvedValueOnce(full as never);
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /notifications/i }));
    expect(await screen.findByText(/most recent/i)).toBeInTheDocument();
  });

  it("does not show the cap note for a short list", async () => {
    apiSpy.mockResolvedValueOnce(NOTIFS as never);
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /notifications/i }));
    await screen.findByText("Welcome to FastAPI");
    expect(screen.queryByText(/most recent/i)).toBeNull();
  });
});
