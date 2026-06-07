import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NotificationsBell } from "@/components/shared/notifications-bell";
import * as apiClient from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";

// The bell gates its pollers on the auth-state signal (`useAuth().user`).
// A signed-in user keeps the existing behaviours working; the 401 test
// below relies on this user being present so the queries are `enabled`.
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: { id: "u1", full_name: "Test Learner", role: "user" },
    token: "tok",
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

type Notif = {
  id: string;
  kind: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
};

const NOTIFS: Notif[] = [
  {
    id: "n1",
    kind: "enrolled",
    title: "Welcome to FastAPI",
    body: "Enjoy the course.",
    data: { course_id: "c1" },
    created_at: new Date().toISOString(),
    read_at: null,
  },
  {
    id: "n2",
    kind: "review_received",
    title: "New review",
    body: "5 stars",
    data: { course_id: "c1" },
    created_at: new Date().toISOString(),
    read_at: new Date().toISOString(),
  },
];

/**
 * Stateful URL-routing API stub. The bell now talks to three reads
 * (unread-count poll, bare list on open) and five mutations; sequencing
 * `mockResolvedValueOnce` per call is too brittle, so route by
 * `METHOD path` instead. Mutations update the closure state so the
 * post-mutation invalidate refetch sees the new world (like the server).
 */
function stubApi(initial: Notif[] = NOTIFS) {
  let items = [...initial];
  const calls: string[] = [];
  const spy = vi.spyOn(apiClient, "api");
  spy.mockImplementation(((path: string, opts?: { method?: string; body?: unknown }) => {
    const route = `${opts?.method ?? "GET"} ${path}`;
    calls.push(route);
    if (route === "GET /api/v1/me/notifications/unread-count") {
      return Promise.resolve({ unread_count: items.filter((n) => !n.read_at).length });
    }
    if (route === "GET /api/v1/me/notifications") {
      return Promise.resolve([...items]);
    }
    if (route === "POST /api/v1/me/notifications/read-all") {
      const touched = items.filter((n) => !n.read_at).length;
      items = items.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() }));
      return Promise.resolve({ ok: true, marked_read: touched });
    }
    if (route === "POST /api/v1/me/notifications/clear") {
      const scope = (opts?.body as { scope?: string })?.scope ?? "read";
      const before = items.length;
      items = scope === "all" ? [] : items.filter((n) => !n.read_at);
      return Promise.resolve({ ok: true, deleted: before - items.length });
    }
    const one = path.match(/^\/api\/v1\/me\/notifications\/([^/]+)(?:\/(read|unread))?$/);
    if (one) {
      const [, id, action] = one;
      if (opts?.method === "DELETE") {
        items = items.filter((n) => n.id !== id);
        return Promise.resolve({ ok: true });
      }
      if (action === "read") {
        items = items.map((n) => (n.id === id ? { ...n, read_at: new Date().toISOString() } : n));
        return Promise.resolve({ ok: true });
      }
      if (action === "unread") {
        items = items.map((n) => (n.id === id ? { ...n, read_at: null } : n));
        return Promise.resolve({ ok: true });
      }
    }
    return Promise.reject(new Error(`unhandled route: ${route}`));
  }) as never);
  return { spy, calls, get items() { return items; } };
}

async function openBell(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /notifications/i }));
  // List loads on open.
  expect(await screen.findByText("Welcome to FastAPI")).toBeInTheDocument();
}

describe("NotificationsBell", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("derives the badge from the unread-count endpoint without fetching the list", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsBell />);
    const btn = await screen.findByRole("button", { name: /1 unread/i });
    expect(btn).toHaveTextContent("1");
    // Closed popover ⇒ the 50-row list was never pulled just for the badge.
    expect(stub.calls).toContain("GET /api/v1/me/notifications/unread-count");
    expect(stub.calls).not.toContain("GET /api/v1/me/notifications");
  });

  it("opens the dropdown, renders rows, and navigating a row marks it read", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await openBell(user);

    await user.click(screen.getByText("Welcome to FastAPI"));
    await waitFor(() => {
      expect(stub.calls).toContain("POST /api/v1/me/notifications/n1/read");
    });
  });

  it("renders the empty state when there are no notifications", async () => {
    stubApi([]);
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /notifications/i }));
    expect(await screen.findByText(/nothing here yet/i)).toBeInTheDocument();
  });

  it("marks everything read via the header action", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await openBell(user);

    await user.click(await screen.findByRole("button", { name: /mark all read/i }));
    await waitFor(() => {
      expect(stub.calls).toContain("POST /api/v1/me/notifications/read-all");
    });
  });

  it("clears read rows behind a confirm dialog", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await openBell(user);

    // n2 is read ⇒ the header shows Clear read; clicking opens the dialog,
    // and only the dialog's destructive confirm fires the request.
    await user.click(screen.getByRole("button", { name: /^clear read$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(stub.calls).not.toContain("POST /api/v1/me/notifications/clear");
    await user.click(within(dialog).getByRole("button", { name: /^clear read$/i }));
    await waitFor(() => {
      expect(stub.calls).toContain("POST /api/v1/me/notifications/clear");
    });
    // Opening the dialog closes the popover (focus moves out). Reopen:
    // the refetched list keeps the unread row and dropped the read one.
    await openBell(user);
    expect(screen.queryByText("New review")).toBeNull();
  });

  it("deletes a row from its kebab menu without navigating", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await openBell(user);

    await user.click(
      screen.getByRole("button", { name: /actions for .*welcome to fastapi/i }),
    );
    await user.click(await screen.findByRole("menuitem", { name: /delete/i }));

    await waitFor(() => {
      expect(stub.calls).toContain("DELETE /api/v1/me/notifications/n1");
    });
    await waitFor(() => {
      expect(screen.queryByText("Welcome to FastAPI")).toBeNull();
    });
    // Deleting never triggers row navigation (no read mark either).
    expect(stub.calls).not.toContain("POST /api/v1/me/notifications/n1/read");
  });

  it("toggles a read row back to unread from the kebab", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await openBell(user);

    await user.click(screen.getByRole("button", { name: /actions for .*new review/i }));
    await user.click(await screen.findByRole("menuitem", { name: /mark unread/i }));
    await waitFor(() => {
      expect(stub.calls).toContain("POST /api/v1/me/notifications/n2/unread");
    });
  });

  it("always offers the View all link to /notifications", async () => {
    stubApi();
    renderWithClient(<NotificationsBell />);
    const user = userEvent.setup();
    await openBell(user);

    const link = screen.getByRole("link", { name: /view all notifications/i });
    expect(link).toHaveAttribute("href", "/notifications");
  });

  it("stops polling the count after a 401 (expired session) instead of looping forever", async () => {
    const spy = vi.spyOn(apiClient, "api");
    spy.mockRejectedValue(
      new ApiError({ status: 401, message: "Unauthorized", code: "unauthorized" }) as never,
    );
    vi.useFakeTimers();
    try {
      renderWithClient(<NotificationsBell />);

      const countCalls = () =>
        spy.mock.calls.filter(([path]) => path === "/api/v1/me/notifications/unread-count")
          .length;
      await vi.waitFor(() => {
        expect(countCalls()).toBeGreaterThan(0);
      });
      const afterFirst = countCalls();

      // Advance well past several 60s poll intervals. If the poller were
      // still armed it would re-hit the endpoint each minute; the 401
      // brake must keep the count flat.
      await vi.advanceTimersByTimeAsync(60_000 * 5);
      expect(countCalls()).toBe(afterFirst);
    } finally {
      vi.useRealTimers();
    }
  });
});
