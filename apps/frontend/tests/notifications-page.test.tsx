import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import NotificationsPage from "@/app/notifications/page";
import * as apiClient from "@/lib/api/client";

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

/** 25 rows: first 5 read, the rest unread — spans two 20-row pages. */
function makeRows(): Notif[] {
  return Array.from({ length: 25 }, (_, i) => ({
    id: `p${i}`,
    kind: "enrolled",
    title: `Notice ${i}`,
    body: "",
    data: { course_id: "c1" },
    created_at: new Date(Date.now() - i * 60_000).toISOString(),
    read_at: i < 5 ? new Date().toISOString() : null,
  }));
}

/** URL-routing stub with real cursor-paging over closure state. */
function stubApi(initial: Notif[] = makeRows()) {
  let items = [...initial];
  const calls: string[] = [];
  const spy = vi.spyOn(apiClient, "api");
  spy.mockImplementation(((path: string, opts?: { method?: string; body?: unknown }) => {
    const route = `${opts?.method ?? "GET"} ${path}`;
    calls.push(route);
    if (route.startsWith("GET /api/v1/me/notifications/unread-count")) {
      return Promise.resolve({ unread_count: items.filter((n) => !n.read_at).length });
    }
    if (route.startsWith("GET /api/v1/me/notifications/inbox")) {
      const url = new URL(`http://x${path}`);
      const unread = url.searchParams.get("unread") === "true";
      const limit = Number(url.searchParams.get("limit") ?? 20);
      const cursor = url.searchParams.get("cursor");
      let pool = unread ? items.filter((n) => !n.read_at) : [...items];
      if (cursor) {
        const at = pool.findIndex((n) => n.id === cursor);
        pool = at === -1 ? pool : pool.slice(at + 1);
      }
      const page = pool.slice(0, limit);
      const next = pool.length > limit ? page[page.length - 1]?.id ?? null : null;
      return Promise.resolve({ items: page, next_cursor: next });
    }
    if (route === "POST /api/v1/me/notifications/read-all") {
      const touched = items.filter((n) => !n.read_at).length;
      items = items.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() }));
      return Promise.resolve({ ok: true, marked_read: touched });
    }
    if (route === "POST /api/v1/me/notifications/clear") {
      const before = items.length;
      items = items.filter((n) => !n.read_at);
      return Promise.resolve({ ok: true, deleted: before - items.length });
    }
    const one = path.match(/^\/api\/v1\/me\/notifications\/([^/]+)(?:\/(read|unread))?$/);
    if (one) {
      const [, id, action] = one;
      if (opts?.method === "DELETE") {
        items = items.filter((n) => n.id !== id);
        return Promise.resolve({ ok: true });
      }
      if (action === "read" || action === "unread") {
        items = items.map((n) =>
          n.id === id
            ? { ...n, read_at: action === "read" ? new Date().toISOString() : null }
            : n,
        );
        return Promise.resolve({ ok: true });
      }
    }
    return Promise.reject(new Error(`unhandled route: ${route}`));
  }) as never);
  return { spy, calls, get items() { return items; } };
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the first page and loads older rows via the cursor", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsPage />);

    expect(await screen.findByText("Notice 0")).toBeInTheDocument();
    expect(screen.getByText("Notice 19")).toBeInTheDocument();
    expect(screen.queryByText("Notice 20")).toBeNull();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /load older/i }));
    expect(await screen.findByText("Notice 24")).toBeInTheDocument();
    // Second fetch carried the cursor of the first page's last row.
    expect(
      stub.calls.some(
        (c) => c.startsWith("GET /api/v1/me/notifications/inbox") && c.includes("cursor=p19"),
      ),
    ).toBe(true);
    // All 25 present, load-more gone (next_cursor null).
    expect(screen.queryByRole("button", { name: /load older/i })).toBeNull();
  });

  it("switches to the unread filter server-side", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsPage />);
    await screen.findByText("Notice 0");

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /unread/i }));

    // Read rows (0-4) disappear; the request carried unread=true.
    await waitFor(() => {
      expect(screen.queryByText("Notice 0")).toBeNull();
    });
    expect(screen.getByText("Notice 5")).toBeInTheDocument();
    expect(
      stub.calls.some(
        (c) => c.startsWith("GET /api/v1/me/notifications/inbox") && c.includes("unread=true"),
      ),
    ).toBe(true);
  });

  it("shows the all-caught-up empty state on the unread tab", async () => {
    stubApi(
      makeRows().map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })),
    );
    renderWithClient(<NotificationsPage />);
    await screen.findByText("Notice 0");

    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: /unread/i }));
    expect(await screen.findByText(/all caught up/i)).toBeInTheDocument();
  });

  it("clears read rows behind the confirm dialog", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsPage />);
    await screen.findByText("Notice 0");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^clear read$/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^clear read$/i }));

    await waitFor(() => {
      expect(stub.calls).toContain("POST /api/v1/me/notifications/clear");
    });
    // The read rows vanish, unread stay.
    await waitFor(() => {
      expect(screen.queryByText("Notice 0")).toBeNull();
    });
    expect(screen.getByText("Notice 5")).toBeInTheDocument();
  });

  it("deletes a row from its kebab without firing navigation or read", async () => {
    const stub = stubApi();
    renderWithClient(<NotificationsPage />);
    await screen.findByText("Notice 0");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /actions for .*notice 7/i }));
    await user.click(await screen.findByRole("menuitem", { name: /delete/i }));

    await waitFor(() => {
      expect(stub.calls).toContain("DELETE /api/v1/me/notifications/p7");
    });
    await waitFor(() => {
      expect(screen.queryByText("Notice 7")).toBeNull();
    });
    expect(stub.calls).not.toContain("POST /api/v1/me/notifications/p7/read");
  });
});
