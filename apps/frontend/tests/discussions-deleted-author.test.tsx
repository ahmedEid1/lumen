/**
 * Discussions tombstoned-author rendering (S7 Gate-B F2).
 *
 * The backend serializes a soft-deleted user through
 * ``UserPublic._anonymize_tombstone`` with ``full_name`` set to the i18n
 * KEY ``"common.deletedUser"`` (a string, NOT null). The discussion pages
 * historically only handled ``author === null``, so a tombstoned (non-null)
 * author would paint the literal key. These specs lock in that BOTH the
 * list and the thread-detail surfaces resolve the tombstone to the shared
 * localized ``common.deletedUser`` label and never leak the raw key.
 */

import { Suspense } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DiscussionsPage from "@/app/courses/[slug]/discussions/page";
import ThreadPage from "@/app/courses/[slug]/discussions/[id]/page";
import { en } from "@/lib/i18n/messages/en";

// Signed-in user so the composer / moderation branches mount without
// affecting the author-name assertions.
vi.mock("@/lib/auth/store", () => ({
  useAuth: () => ({
    user: { id: "viewer", full_name: "Viewer", role: "student", avatar_url: null },
    token: "tk_test",
    ready: true,
  }),
}));

// The pages call ``api`` from the client directly (not the endpoints
// module). Route each URL to a fixture; the tombstoned author carries the
// i18n KEY in ``full_name`` exactly as the backend serializer emits it.
const TOMBSTONE = "common.deletedUser";
const api = vi.fn();
vi.mock("@/lib/api/client", () => ({
  api: (...args: unknown[]) => api(...args),
}));

const COURSE = { id: "c1", title: "Algorithms", slug: "algorithms", owner: { id: "owner1" } };

beforeEach(() => {
  api.mockReset();
});

// The pages unwrap their route params via React 19 ``use(params)`` on a
// promise, which suspends until the promise resolves. Render inside an async
// ``act`` (mirrors studio-editor-lifecycle.test.tsx) so the suspense + the
// initial course/threads queries flush before assertions run.
async function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <Suspense fallback={null}>{ui}</Suspense>
      </QueryClientProvider>,
    );
  });
}

describe("Discussions list — tombstoned author (S7 F2)", () => {
  it("renders the localized deleted-user label for a tombstoned thread author", async () => {
    const threads = {
      items: [
        {
          id: "th1",
          title: "Big-O analysis",
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
          reply_count: 0,
          last_activity_at: "2026-05-01T00:00:00Z",
          author: { id: "ghost", full_name: TOMBSTONE, avatar_url: null },
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    };
    api.mockImplementation((url: string) => {
      if (url.includes("/discussions")) return Promise.resolve(threads);
      return Promise.resolve(COURSE);
    });

    await renderWithClient(
      <DiscussionsPage params={Promise.resolve({ slug: "algorithms" })} />,
    );

    expect(await screen.findByText("Big-O analysis")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(en["common.deletedUser"]))).toBeInTheDocument();
    // The raw i18n key must never reach the DOM.
    expect(screen.queryByText(new RegExp(TOMBSTONE))).not.toBeInTheDocument();
  });
});

describe("Thread detail — tombstoned author (S7 F2)", () => {
  it("resolves the tombstone for the opening post and a reply author", async () => {
    const thread = {
      id: "th1",
      course_id: "c1",
      title: "Big-O analysis",
      body: "How do I reason about O(n log n)?",
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z",
      author: { id: "ghost", full_name: TOMBSTONE, avatar_url: null },
      replies: [
        {
          id: "r1",
          body: "Start with the recurrence.",
          created_at: "2026-05-02T00:00:00Z",
          updated_at: "2026-05-02T00:00:00Z",
          author: { id: "ghost2", full_name: TOMBSTONE, avatar_url: null },
        },
      ],
    };
    api.mockImplementation((url: string) => {
      if (url.startsWith("/api/v1/discussions/")) return Promise.resolve(thread);
      return Promise.resolve(COURSE);
    });

    await renderWithClient(
      <ThreadPage params={Promise.resolve({ slug: "algorithms", id: "th1" })} />,
    );

    expect(await screen.findByText("Big-O analysis")).toBeInTheDocument();
    // Two surfaces (opening post + reply) both show the shared localized label.
    await waitFor(() =>
      expect(screen.getAllByText(en["common.deletedUser"]).length).toBe(2),
    );
    expect(screen.queryByText(new RegExp(TOMBSTONE))).not.toBeInTheDocument();
  });
});
