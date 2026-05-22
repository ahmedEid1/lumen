/**
 * Course-scoped tutor panel (Phase E1).
 *
 * The component owns the chat surface — it opens a conversation on
 * mount, optimistically renders the user's turn the moment they hit
 * Send, shows a loading state while the round-trip is in flight, and
 * renders the assistant's reply with its citation pills when it
 * lands. This spec wires the Tutor API client through Vitest spies
 * and asserts each of those four behaviours.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TutorPanel } from "@/components/tutor/tutor-panel";
import * as endpoints from "@/lib/api/endpoints";
import type {
  TutorConversationDetail,
  TutorPostResponse,
} from "@/lib/api/endpoints";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const FRESH_CONVERSATION: TutorConversationDetail = {
  id: "conv_1",
  course_id: "c1",
  created_at: new Date("2026-05-22T10:00:00Z").toISOString(),
  last_message_at: new Date("2026-05-22T10:00:00Z").toISOString(),
  messages: [],
};

describe("TutorPanel", () => {
  let startSpy: ReturnType<typeof vi.spyOn>;
  let postSpy: ReturnType<typeof vi.spyOn>;
  let getSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    startSpy = vi
      .spyOn(endpoints.Tutor, "startConversation")
      .mockResolvedValue(FRESH_CONVERSATION as never);
    getSpy = vi
      .spyOn(endpoints.Tutor, "getConversation")
      .mockResolvedValue(FRESH_CONVERSATION as never);
    postSpy = vi.spyOn(endpoints.Tutor, "postMessage");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens a fresh conversation on mount and shows the empty prompt", async () => {
    renderWithClient(<TutorPanel courseId="c1" />);

    await waitFor(() => {
      expect(startSpy).toHaveBeenCalledWith("c1");
    });
    expect(
      screen.getByText(/ask anything about this course/i),
    ).toBeInTheDocument();
  });

  it("optimistically renders the user message, shows a loading state, then renders the assistant reply with citations", async () => {
    let resolvePost: (value: TutorPostResponse) => void = () => undefined;
    postSpy.mockImplementation(
      () =>
        new Promise<TutorPostResponse>((resolve) => {
          resolvePost = resolve;
        }) as never,
    );

    renderWithClient(<TutorPanel courseId="c1" />);

    await waitFor(() => expect(startSpy).toHaveBeenCalled());

    const composer = screen.getByPlaceholderText(/type your question/i);
    const user = userEvent.setup();
    await user.type(composer, "What powers the cell?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    // 1) Optimistic user message appears immediately.
    await waitFor(() => {
      expect(screen.getByText("What powers the cell?")).toBeInTheDocument();
    });

    // 2) Loading sentinel renders while the round-trip is in flight.
    expect(screen.getByTestId("tutor-loading")).toBeInTheDocument();

    // 3) Land the server response — both turns + a citation.
    resolvePost({
      user_message: {
        id: "m_user",
        role: "user",
        content: "What powers the cell?",
        citations: [],
        created_at: new Date().toISOString(),
      },
      assistant_message: {
        id: "m_asst",
        role: "assistant",
        content: "Mitochondria. They generate ATP via cellular respiration.",
        citations: [
          {
            lesson_id: "lsn_a",
            lesson_title: "Cell biology basics",
            chunk_excerpt:
              "The mitochondria is the powerhouse of the cell …",
          },
        ],
        created_at: new Date().toISOString(),
      },
      refused: false,
    });

    // Assistant reply lands.
    await waitFor(() => {
      expect(
        screen.getByText(/mitochondria\. they generate atp/i),
      ).toBeInTheDocument();
    });

    // Loading sentinel disappears.
    expect(screen.queryByTestId("tutor-loading")).not.toBeInTheDocument();

    // Citation pill rendered, pointing at the lesson.
    const citations = screen.getByTestId("tutor-citations");
    const pill = within(citations).getByText("Cell biology basics");
    expect(pill).toBeInTheDocument();
    expect(pill.closest("a")).toHaveAttribute(
      "href",
      "/courses/lessons/lsn_a",
    );

    expect(postSpy).toHaveBeenCalledWith("conv_1", "What powers the cell?");
    // The component fetches the persisted conversation after a
    // successful send so a future "reload" reflects server state.
    expect(getSpy).toHaveBeenCalled();
  });

  it("blocks Send until there is non-blank input", async () => {
    renderWithClient(<TutorPanel courseId="c1" />);
    await waitFor(() => expect(startSpy).toHaveBeenCalled());
    const submit = screen.getByRole("button", { name: /send/i });
    expect(submit).toBeDisabled();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText(/type your question/i), "hi");
    expect(submit).not.toBeDisabled();
  });
});
