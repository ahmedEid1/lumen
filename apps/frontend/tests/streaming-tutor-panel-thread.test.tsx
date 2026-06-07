/**
 * Regression: a multi-question streaming session must stay ONE thread.
 *
 * Until the 2026-06-06 persistence fix the panel sent only
 * `{content, course_slug}` on every POST /tutor/turns — the server
 * neither created nor received a conversation, so streamed messages had
 * nowhere to persist (history empty after reload; BACKLOG P2). The
 * server now auto-creates a conversation on the first course-scoped
 * turn and returns it on the TurnOut; the panel must echo that
 * `conversation_id` back on follow-up sends so question #2 lands in the
 * same persisted thread instead of forking a new conversation per turn.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/auth/store", () => ({ useAuth: () => ({ token: "tok" }) }));

// Keep the SSE machinery out of the test — the panel only needs a
// settled phase so the composer stays enabled between sends.
vi.mock("@/lib/tutor/use-tutor-stream", () => ({
  useTutorStream: () => ({
    phase: "idle",
    tools: [],
    text: "",
    error: null,
  }),
}));

import { StreamingTutorPanel } from "@/components/tutor/streaming-tutor-panel";

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <StreamingTutorPanel courseId="crs_1" courseSlug="rag-from-scratch" />
    </QueryClientProvider>,
  );
}

type HistoryFixture = {
  items: Array<Record<string, unknown>>;
  detail?: Record<string, unknown>;
};

/** Global fetch stub covering the panel's three wire surfaces:
 * POST /tutor/turns (captured into `bodies`), the mount-time
 * conversations list + detail (from `history`), and a benign empty
 * payload for everything else (chip-rail library etc.). */
function stubFetch(bodies: Array<Record<string, unknown>>, history: HistoryFixture) {
  const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const href = String(url);
    if (href.endsWith("/api/v1/tutor/turns") && init?.method === "POST") {
      bodies.push(JSON.parse(String(init.body)));
      return new Response(
        JSON.stringify({
          id: `turn-${bodies.length}`,
          status: "pending",
          conversation_id: "conv-123",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    }
    if (href.includes("/api/v1/courses/") && href.includes("/tutor/conversations")) {
      return new Response(
        JSON.stringify({
          items: history.items,
          total: history.items.length,
          page: 1,
          page_size: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (href.includes("/api/v1/tutor/conversations/") && history.detail) {
      return new Response(JSON.stringify(history.detail), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ items: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const CONV_SUMMARY = {
  id: "conv-123",
  course_id: "crs_1",
  created_at: "2026-06-07T08:00:00Z",
  last_message_at: "2026-06-07T08:01:00Z",
  last_message_preview: "Because…",
  message_count: 2,
};

const CONV_DETAIL = {
  id: "conv-123",
  course_id: "crs_1",
  created_at: "2026-06-07T08:00:00Z",
  last_message_at: "2026-06-07T08:01:00Z",
  messages: [
    {
      id: "m1",
      role: "user",
      content: "Why chunk documents?",
      citations: [],
      created_at: "2026-06-07T08:00:30Z",
    },
    {
      id: "m2",
      role: "assistant",
      content: "Because focused embeddings retrieve better [L:lsn_1].",
      citations: [
        { lesson_id: "lsn_1", lesson_title: "Chunking 101", chunk_excerpt: "…" },
      ],
      created_at: "2026-06-07T08:01:00Z",
    },
  ],
};

describe("StreamingTutorPanel — history on reopen", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the latest thread's persisted messages on mount", async () => {
    stubFetch([], { items: [CONV_SUMMARY], detail: CONV_DETAIL });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByTestId("tutor-message-user")).toBeInTheDocument();
    });
    expect(screen.getByTestId("tutor-message-user")).toHaveTextContent(
      "Why chunk documents?",
    );
    expect(screen.getByTestId("tutor-message-assistant")).toHaveTextContent(
      "Because focused embeddings retrieve better",
    );
    // citation pill rendered from the persisted citations
    expect(screen.getByTestId("tutor-citations")).toHaveTextContent("Chunking 101");
    // empty-state prompt must NOT show over real history
    expect(screen.queryByText("Ask anything about this course", { exact: false })).toBeNull();
  });

  it("keeps the empty state when no thread exists", async () => {
    const fetchMock = stubFetch([], { items: [] });
    renderPanel();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([u]) => String(u).includes("/tutor/conversations")),
      ).toBe(true);
    });
    expect(screen.queryByTestId("tutor-message-user")).toBeNull();
  });

  it("continues the SAME thread after reload (adopts the latest conversation id)", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    stubFetch(bodies, { items: [CONV_SUMMARY], detail: CONV_DETAIL });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("tutor-message-user")).toBeInTheDocument();
    });

    const user = userEvent.setup();
    const composer = screen.getByRole("textbox");
    await user.type(composer, "And what about overlap?");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(1));
    // the VERY FIRST post-reload send already carries the adopted thread id
    expect(bodies[0]).toEqual({
      content: "And what about overlap?",
      course_slug: "rag-from-scratch",
      conversation_id: "conv-123",
    });
  });
});

describe("StreamingTutorPanel — conversation threading", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("echoes the server-assigned conversation_id on follow-up turns", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const href = String(url);
      // Only the turn POSTs are under test — the panel makes unrelated
      // GETs (question-library chip rail) through the same global fetch.
      if (href.endsWith("/api/v1/tutor/turns") && init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)));
        return new Response(
          JSON.stringify({
            id: `turn-${bodies.length}`,
            status: "pending",
            conversation_id: "conv-123",
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();
    const user = userEvent.setup();
    const composer = screen.getByRole("textbox");
    // The composer is held while the mount-time thread lookup is in
    // flight (pre-adoption sends would fork a new conversation).
    await waitFor(() => expect(composer).toBeEnabled());

    await user.type(composer, "Why chunk documents?");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(1));
    // First send: fresh thread — no conversation_id, course context only.
    expect(bodies[0]).toEqual({
      content: "Why chunk documents?",
      course_slug: "rag-from-scratch",
    });

    await user.type(composer, "And what about overlap?");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(bodies).toHaveLength(2));
    // Follow-up: same thread.
    expect(bodies[1]).toEqual({
      content: "And what about overlap?",
      course_slug: "rag-from-scratch",
      conversation_id: "conv-123",
    });
  });
});
