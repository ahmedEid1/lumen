/**
 * Agent-reasoning panel (Lumen v2 Phase I2).
 *
 * The "agent thinking" surface that lives under each assistant
 * tutor turn. Pin the four behaviours that make this the
 * project's recruiter-facing moat:
 *
 *  1. The confidence badge renders the supplied 0-5 score.
 *  2. The tabular plan shows one row per tool call, with the
 *     tool name + rationale + result summary.
 *  3. Each row is expandable; expansion reveals the per-tool
 *     details (chunks for retriever, snippets for web searcher, ...).
 *  4. ``defaultExpanded`` pre-opens the panel for the first tutor
 *     turn on page load so the agent's reasoning is visible
 *     without a click.
 */

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AgentReasoningPanel,
  type ToolCallTrace,
} from "@/components/tutor/agent-reasoning-panel";

const RETRIEVER_TRACE: ToolCallTrace = {
  tool_name: "retriever",
  args: { query: "cell biology" },
  rationale: "Direct course-content lookup.",
  result_summary: "found 2 chunk(s) across 2 lesson(s)",
  result_details: {
    chunks: [
      {
        lesson_id: "lsn_a",
        lesson_title: "Cell basics",
        text: "Cells are the basic unit of life.",
        score: 0.12,
      },
      {
        lesson_id: "lsn_b",
        lesson_title: "Organelles",
        text: "Mitochondria generate ATP.",
        score: 0.31,
      },
    ],
    citations: ["lsn_a", "lsn_b"],
  },
};

const WEB_TRACE: ToolCallTrace = {
  tool_name: "web_searcher",
  args: { query: "latest cell biology research" },
  rationale: "User asked about a current discovery.",
  result_summary: "found 1 web snippet(s)",
  result_details: {
    snippets: [
      {
        title: "New organelle discovered",
        url: "https://example.com/article",
        content_first_240: "Scientists identified a new organelle...",
      },
    ],
    citations: ["https://example.com/article"],
  },
};

const CODE_TRACE: ToolCallTrace = {
  tool_name: "code_runner",
  args: { code: "print(2 + 2)" },
  rationale: "Quick arithmetic check.",
  result_summary: "exit=0; stdout='4\\n'",
  result_details: {
    stdout: "4\n",
    exit_code: 0,
    error_msg: null,
  },
};

describe("AgentReasoningPanel", () => {
  it("returns nothing when the tool-call list is empty", () => {
    const { container } = render(
      <AgentReasoningPanel toolCalls={[]} confidence={0} />,
    );
    // Refused / empty-retrieval turns should not render the panel
    // at all — keeps the UX quiet when there is nothing to show.
    expect(container.firstChild).toBeNull();
  });

  it("renders the confidence badge with the supplied score", () => {
    render(
      <AgentReasoningPanel
        toolCalls={[RETRIEVER_TRACE]}
        confidence={4}
        defaultExpanded={false}
      />,
    );
    expect(screen.getByTestId("agent-trace-confidence")).toHaveTextContent(
      "4/5",
    );
  });

  it("renders one row per tool call with the rationale and summary", async () => {
    render(
      <AgentReasoningPanel
        toolCalls={[RETRIEVER_TRACE, WEB_TRACE, CODE_TRACE]}
        confidence={5}
        defaultExpanded
      />,
    );
    const rows = screen.getAllByTestId("agent-trace-row");
    expect(rows).toHaveLength(3);

    // First row: retriever.
    expect(within(rows[0]).getByText("retriever")).toBeInTheDocument();
    expect(
      within(rows[0]).getByText("Direct course-content lookup."),
    ).toBeInTheDocument();
    expect(
      within(rows[0]).getByText(/found 2 chunk\(s\)/),
    ).toBeInTheDocument();

    // Second row: web_searcher.
    expect(within(rows[1]).getByText("web_searcher")).toBeInTheDocument();
    expect(
      within(rows[1]).getByText("User asked about a current discovery."),
    ).toBeInTheDocument();

    // Third row: code_runner.
    expect(within(rows[2]).getByText("code_runner")).toBeInTheDocument();
  });

  it("expands a row on click and reveals the per-tool details", async () => {
    render(
      <AgentReasoningPanel
        toolCalls={[RETRIEVER_TRACE]}
        confidence={4}
        defaultExpanded
      />,
    );
    // Details are not visible before the user clicks the row.
    expect(
      screen.queryByTestId("agent-trace-row-details"),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("agent-trace-row"));

    const details = screen.getByTestId("agent-trace-row-details");
    expect(details).toBeInTheDocument();
    // Retriever details surface the lesson id + title + text.
    expect(within(details).getByText(/L:lsn_a/)).toBeInTheDocument();
    expect(
      within(details).getByText(/Cells are the basic unit of life/),
    ).toBeInTheDocument();
  });

  it("auto-expands the table when defaultExpanded is true", () => {
    render(
      <AgentReasoningPanel
        toolCalls={[RETRIEVER_TRACE]}
        confidence={4}
        defaultExpanded
      />,
    );
    // Trace rows render without the user clicking the disclosure.
    expect(screen.getByTestId("agent-trace-rows")).toBeInTheDocument();
    expect(screen.getByTestId("agent-trace-row")).toBeInTheDocument();
  });

  it("collapses the table when defaultExpanded is false", () => {
    render(
      <AgentReasoningPanel
        toolCalls={[RETRIEVER_TRACE]}
        confidence={4}
        defaultExpanded={false}
      />,
    );
    expect(
      screen.queryByTestId("agent-trace-rows"),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-trace-toggle")).toBeInTheDocument();
  });

  it("toggle button opens the table on click", async () => {
    render(
      <AgentReasoningPanel
        toolCalls={[RETRIEVER_TRACE]}
        confidence={3}
        defaultExpanded={false}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId("agent-trace-toggle"));
    expect(screen.getByTestId("agent-trace-rows")).toBeInTheDocument();
  });
});
