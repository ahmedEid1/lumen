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
