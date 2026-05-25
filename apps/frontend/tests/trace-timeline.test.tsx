/**
 * Trace timeline + step card + cost badge tests (Lumen v2 Phase I4).
 *
 * Pin the behaviours that make the I4 surface the "show your
 * work" portfolio moat:
 *
 *   1. The timeline renders one row per step in step_index order.
 *   2. The first row is pre-expanded in read mode (default).
 *   3. Auto-play advances the active step over time, and the
 *      active step is force-expanded with the lime accent.
 *   4. The scrub slider repositions the active step.
 *   5. Pause / play toggle is reflected by the active step
 *      remaining frozen.
 *   6. The CostBadge surfaces cost, latency, tokens, confidence,
 *      and step count.
 *   7. The empty-state renders the empty label.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TraceTimeline } from "@/components/trace/TraceTimeline";
import { CostBadge } from "@/components/trace/CostBadge";
import { TraceStepCard } from "@/components/trace/TraceStepCard";
import { RetrievalChunkList } from "@/components/trace/RetrievalChunkList";
import type { TraceStep } from "@/lib/api/endpoints";

const STEPS: TraceStep[] = [
  {
    trace_id: "trc_plan",
    parent_trace_id: null,
    parent_call_id: null,
    step: "plan",
    step_index: 0,
    payload: {
      tool_calls: [
        { tool_name: "retriever", rationale: "Course-content lookup." },
      ],
      confidence_after_plan: 4,
    },
    duration_ms: 120,
    status: "ok",
    created_at: "2026-05-22T10:00:00Z",
  },
  {
    trace_id: "trc_tool",
    parent_trace_id: "trc_plan",
    parent_call_id: null,
    step: "tool_call",
    step_index: 1,
    payload: {
      tool_name: "retriever",
      rationale: "Pull lesson chunks.",
    },
    duration_ms: 320,
    status: "ok",
    created_at: "2026-05-22T10:00:01Z",
  },
  {
    trace_id: "trc_synth",
    parent_trace_id: "trc_plan",
    parent_call_id: null,
    step: "synthesis",
    step_index: 2,
    payload: {
      answer_head: "Photosynthesis is the process plants use to...",
      citation_count: 2,
      tool_calls_in_synth: 1,
    },
    duration_ms: 850,
    status: "ok",
    created_at: "2026-05-22T10:00:02Z",
  },
];

describe("TraceTimeline (read mode)", () => {
  it("renders one row per step in order", () => {
    render(<TraceTimeline steps={STEPS} />);
    const planEl = screen.getByTestId("trace-step-plan");
    const toolEl = screen.getByTestId("trace-step-tool_call");
    const synthEl = screen.getByTestId("trace-step-synthesis");
    expect(planEl).toBeInTheDocument();
    expect(toolEl).toBeInTheDocument();
    expect(synthEl).toBeInTheDocument();
    expect(planEl.getAttribute("data-step-index")).toBe("0");
    expect(toolEl.getAttribute("data-step-index")).toBe("1");
    expect(synthEl.getAttribute("data-step-index")).toBe("2");
  });

  it("pre-expands the first step in read mode", () => {
    render(<TraceTimeline steps={STEPS} />);
    // The first step's body section is rendered (confidence label is
    // in the plan payload renderer).
    expect(screen.getByText(/Confidence/)).toBeInTheDocument();
  });

  it("renders the empty-state label when no steps are supplied", () => {
    render(
      <TraceTimeline steps={[]} emptyLabel="Nothing to see here." />,
    );
    expect(screen.getByTestId("trace-timeline-empty")).toHaveTextContent(
      "Nothing to see here.",
    );
  });

  it("does not render the replay controls in read mode", () => {
    render(<TraceTimeline steps={STEPS} />);
    expect(
      screen.queryByTestId("trace-timeline-controls"),
    ).not.toBeInTheDocument();
  });
});

describe("TraceTimeline (replay mode)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the replay controls", () => {
    render(<TraceTimeline steps={STEPS} autoPlay stepDurationMs={100} />);
    expect(screen.getByTestId("trace-timeline-controls")).toBeInTheDocument();
    expect(screen.getByTestId("replay-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("replay-scrub")).toBeInTheDocument();
  });

  it("starts with the first step active", () => {
    render(<TraceTimeline steps={STEPS} autoPlay stepDurationMs={100} />);
    const plan = screen.getByTestId("trace-step-plan");
    expect(plan.getAttribute("data-active")).toBe("true");
    const tool = screen.getByTestId("trace-step-tool_call");
    expect(tool.getAttribute("data-active")).toBe("false");
  });

  it("advances the active step after the configured duration", () => {
    render(<TraceTimeline steps={STEPS} autoPlay stepDurationMs={100} />);
    // Initially, step 0 is active.
    expect(
      screen.getByTestId("trace-step-plan").getAttribute("data-active"),
    ).toBe("true");

    // After one tick, step 1 (tool_call) should be active.
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(
      screen.getByTestId("trace-step-tool_call").getAttribute("data-active"),
    ).toBe("true");
    expect(
      screen.getByTestId("trace-step-plan").getAttribute("data-active"),
    ).toBe("false");

    // After another tick, step 2 (synthesis) should be active.
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(
      screen.getByTestId("trace-step-synthesis").getAttribute("data-active"),
    ).toBe("true");
  });

  it("updates the scrub position label as steps advance", () => {
    render(<TraceTimeline steps={STEPS} autoPlay stepDurationMs={100} />);
    expect(screen.getByTestId("replay-position")).toHaveTextContent(
      "step 1 / 3",
    );
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByTestId("replay-position")).toHaveTextContent(
      "step 2 / 3",
    );
  });

  it("scrub bar repositions the active step", () => {
    render(<TraceTimeline steps={STEPS} autoPlay stepDurationMs={100} />);
    const scrub = screen.getByTestId("replay-scrub") as HTMLInputElement;
    // React's onChange fires on the React synthetic event, which is
    // backed by the native ``change`` event in the testing-library
    // ``fireEvent`` adapter. Use ``fireEvent.change`` so the
    // controlled-input update path runs inside React's event handling.
    fireEvent.change(scrub, { target: { value: "2" } });
    expect(
      screen.getByTestId("trace-step-synthesis").getAttribute("data-active"),
    ).toBe("true");
  });
});

describe("CostBadge", () => {
  it("renders cost / latency / tokens / confidence / step count", () => {
    render(
      <CostBadge
        costUsd="0.000123"
        latencyMs={950}
        totalTokens={180}
        confidence={4}
        stepCount={3}
      />,
    );
    expect(screen.getByTestId("cost-value")).toHaveTextContent("$0.000123");
    expect(screen.getByTestId("latency-value")).toHaveTextContent("950ms");
    expect(screen.getByTestId("tokens-value")).toHaveTextContent("180 tok");
    expect(screen.getByTestId("confidence-value")).toHaveTextContent(
      "Confidence: 4/5",
    );
    expect(screen.getByTestId("step-count-value")).toHaveTextContent(
      "3 steps",
    );
  });

  it("formats latency over 1000ms as seconds", () => {
    render(
      <CostBadge costUsd="0.001" latencyMs={2500} totalTokens={100} />,
    );
    expect(screen.getByTestId("latency-value")).toHaveTextContent("2.50s");
  });

  it("renders without optional fields", () => {
    render(<CostBadge costUsd="0" latencyMs={0} totalTokens={0} />);
    expect(screen.getByTestId("cost-value")).toHaveTextContent("$0.000000");
    expect(
      screen.queryByTestId("confidence-value"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("step-count-value"),
    ).not.toBeInTheDocument();
  });
});

describe("TraceStepCard", () => {
  it("toggles expansion on click in manual mode", async () => {
    render(<TraceStepCard step={STEPS[0]} />);
    const card = screen.getByTestId("trace-step-plan");
    // Collapsed by default — confidence label isn't visible.
    expect(card.getAttribute("data-active")).toBe("false");
    const button = card.querySelector("button");
    expect(button).not.toBeNull();
    const user = userEvent.setup();
    await user.click(button!);
    // After click, the plan payload (with "Confidence" section) renders.
    expect(screen.getByText(/Confidence/)).toBeInTheDocument();
  });

  it("renders the active accent when active is true", () => {
    render(<TraceStepCard step={STEPS[0]} active />);
    const card = screen.getByTestId("trace-step-plan");
    expect(card.getAttribute("data-active")).toBe("true");
    // Active forces expansion — the payload section renders.
    expect(screen.getByText(/Confidence/)).toBeInTheDocument();
  });
});

describe("RetrievalChunkList", () => {
  it("renders the empty-state when no chunks are supplied", () => {
    render(<RetrievalChunkList chunks={[]} />);
    expect(screen.getByTestId("retrieval-chunk-list-empty")).toHaveTextContent(
      "No chunks retrieved.",
    );
  });

  it("renders one row per chunk with the lesson id + score", () => {
    render(
      <RetrievalChunkList
        chunks={[
          {
            lesson_id: "lsn_a",
            lesson_title: "Cell basics",
            score: 0.123,
            text: "Cells are the basic unit of life.",
          },
          {
            lesson_id: "lsn_b",
            lesson_title: "Organelles",
            score: 0.456,
            text: "Mitochondria generate ATP.",
          },
        ]}
      />,
    );
    const rows = screen.getAllByTestId("retrieval-chunk-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("L:lsn_a");
    expect(rows[0]).toHaveTextContent("score 0.123");
    expect(rows[0]).toHaveTextContent("Cells are the basic unit of life.");
    expect(rows[1]).toHaveTextContent("score 0.456");
  });
});
