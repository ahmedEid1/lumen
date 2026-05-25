/**
 * Studio draft-trace timeline (Lumen v2 Phase I3).
 *
 * Pin the four behaviours the recruiter-facing surface relies on:
 *
 *  1. Empty steps render an empty-state, not an exception.
 *  2. Every step kind in the fixture renders one row, in the order
 *     the orchestrator emitted them.
 *  3. A row's payload (prompt / response / critic scores / weak
 *     spots) is hidden until the user clicks the row header.
 *  4. The final score badge maps mean → variant (good / warn / bad)
 *     so the publish-anyway CTA is colour-coded honestly.
 */

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  DraftTraceTimeline,
  FinalScoreBadge,
} from "@/app/studio/draft/[courseId]/components/draft-trace-timeline";
import type { DraftTraceStep } from "@/lib/api/endpoints";

const FIXTURE_STEPS: DraftTraceStep[] = [
  {
    id: "trc_1",
    draft_id: "draft_abc",
    course_id: null,
    step: "researcher",
    step_index: 0,
    status: "ok",
    duration_ms: 412,
    payload: {
      prompt_summary: "Teach FastAPI to absolute beginners.",
      response_summary: "3 web snippet(s); 2 catalog neighbour(s)",
      web_snippets: [],
      catalog_neighbours: [],
    },
    created_at: "2026-07-13T12:00:00Z",
  },
  {
    id: "trc_2",
    draft_id: "draft_abc",
    course_id: null,
    step: "outliner",
    step_index: 1,
    status: "ok",
    duration_ms: 1820,
    payload: {
      prompt_summary: "Teach FastAPI to absolute beginners.",
      response_summary: "FastAPI in 90 Minutes — 3 module(s), 9 lesson(s)",
    },
    created_at: "2026-07-13T12:00:02Z",
  },
  {
    id: "trc_3",
    draft_id: "draft_abc",
    course_id: null,
    step: "critic",
    step_index: 2,
    status: "ok",
    duration_ms: 510,
    payload: {
      prompt_summary: "FastAPI in 90 Minutes — outline...",
      response_summary: "The arc is uneven; module 2 jumps ahead.",
      critic_scores: { coverage: 4, learning_arc: 3, scope: 4 },
      weak_spots: ["Module 2 jumps ahead of the foundations."],
      revision_number: 0,
    },
    created_at: "2026-07-13T12:00:03Z",
  },
  {
    id: "trc_4",
    draft_id: "draft_abc",
    course_id: null,
    step: "reviser",
    step_index: 3,
    status: "ok",
    duration_ms: 2100,
    payload: {
      prompt_summary: "Module 2 jumps ahead of the foundations.",
      response_summary:
        "FastAPI in 90 Minutes — revised — 3 module(s), 10 lesson(s)",
      revision_number: 1,
    },
    created_at: "2026-07-13T12:00:05Z",
  },
  {
    id: "trc_5",
    draft_id: "draft_abc",
    course_id: "crs_xyz",
    step: "lesson_drafter",
    step_index: 4,
    status: "ok",
    duration_ms: 1200,
    payload: {
      prompt_summary: "Install Python 3.13",
      response_summary: "text lesson drafted",
      lesson_id: "lsn_install",
      lesson_type: "text",
    },
    created_at: "2026-07-13T12:00:07Z",
  },
  {
    id: "trc_6",
    draft_id: "draft_abc",
    course_id: "crs_xyz",
    step: "final_critic",
    step_index: 5,
    status: "ok",
    duration_ms: 600,
    payload: {
      prompt_summary: "FastAPI in 90 Minutes — full course...",
      response_summary: "Ready to publish.",
      critic_scores: { coverage: 5, learning_arc: 4, scope: 5 },
      weak_spots: [],
    },
    created_at: "2026-07-13T12:00:08Z",
  },
];

describe("DraftTraceTimeline", () => {
  it("renders an empty state when no steps are provided", () => {
    render(<DraftTraceTimeline steps={[]} />);
    expect(screen.queryByTestId("draft-trace-timeline")).not.toBeInTheDocument();
    expect(
      screen.getByText(/No trace recorded for this course yet/i),
    ).toBeInTheDocument();
  });

  it("renders one row per step in the supplied order", () => {
    render(<DraftTraceTimeline steps={FIXTURE_STEPS} />);
    const timeline = screen.getByTestId("draft-trace-timeline");
    const items = within(timeline).getAllByRole("listitem");
    expect(items).toHaveLength(FIXTURE_STEPS.length);
    expect(items[0]).toHaveAttribute("data-step", "researcher");
    expect(items[1]).toHaveAttribute("data-step", "outliner");
    expect(items[2]).toHaveAttribute("data-step", "critic");
    expect(items[3]).toHaveAttribute("data-step", "reviser");
    expect(items[4]).toHaveAttribute("data-step", "lesson_drafter");
    expect(items[5]).toHaveAttribute("data-step", "final_critic");
  });

  it("hides the payload until the row header is clicked", async () => {
    render(<DraftTraceTimeline steps={FIXTURE_STEPS} />);
    const u = userEvent.setup();
    // Before click: critic's weak-spot text is not in the DOM.
    expect(
      screen.queryByText(/Module 2 jumps ahead of the foundations/),
    ).not.toBeInTheDocument();
    const criticRow = screen.getByTestId("draft-trace-step-critic");
    const button = within(criticRow).getByRole("button");
    await u.click(button);
    // After click: the weak-spot text is visible.
    expect(
      within(criticRow).getByText(/Module 2 jumps ahead of the foundations/),
    ).toBeInTheDocument();
  });

  it("shows the step name and the per-step duration", () => {
    render(<DraftTraceTimeline steps={FIXTURE_STEPS} />);
    const researcherRow = screen.getByTestId("draft-trace-step-researcher");
    expect(within(researcherRow).getByText("Researcher")).toBeInTheDocument();
    expect(within(researcherRow).getByText("412ms")).toBeInTheDocument();
  });
});

describe("FinalScoreBadge", () => {
  it("renders the mean and the three-axis breakdown", () => {
    render(
      <FinalScoreBadge
        score={{
          coverage: 5,
          learning_arc: 4,
          scope: 5,
          mean: 4.67,
          rationale: "Ready to publish.",
        }}
      />,
    );
    const badge = screen.getByTestId("draft-trace-final-score");
    expect(badge).toHaveAttribute("data-variant", "good");
    expect(within(badge).getByText(/4\.67/)).toBeInTheDocument();
    expect(within(badge).getByText(/coverage 5/)).toBeInTheDocument();
    expect(within(badge).getByText(/Ready to publish/i)).toBeInTheDocument();
  });

  it("maps mean ∈ [3, 4) to the warn variant", () => {
    render(
      <FinalScoreBadge
        score={{
          coverage: 3,
          learning_arc: 3,
          scope: 4,
          mean: 3.33,
          rationale: "Mediocre.",
        }}
      />,
    );
    expect(
      screen.getByTestId("draft-trace-final-score"),
    ).toHaveAttribute("data-variant", "warn");
  });

  it("maps mean < 3 to the bad variant", () => {
    render(
      <FinalScoreBadge
        score={{
          coverage: 2,
          learning_arc: 2,
          scope: 2,
          mean: 2.0,
          rationale: "Needs work.",
        }}
      />,
    );
    expect(
      screen.getByTestId("draft-trace-final-score"),
    ).toHaveAttribute("data-variant", "bad");
  });
});
