/**
 * L27 + L41-followup — public /eval surface.
 *
 * L27 shipped this as honest-empty (no fetch). L41 wires it to
 * `GET /api/v1/eval/public` — when at least one suite is promoted,
 * the page swaps the placeholder for a SuiteCard. Tests cover both
 * states: empty (no fetch resolution / null suites) and live
 * (promoted suite with axes + judge metadata).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { EvalPublicView } from "@/app/eval/eval-public-view";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

const emptySuites = () => ({
  json: async () => ({
    suites: { tutor: null, authoring: null, ingest: null },
  }),
  ok: true,
});

const promotedTutor = () => ({
  json: async () => ({
    suites: {
      tutor: {
        suite: "tutor",
        mean_overall: 1.23,
        axes: { grounding: 1.5, accuracy: 1.0, style: 1.2 },
        items_judged: 10,
        finished_at: "2026-05-27T15:09:55Z",
        judge_provider: "openai-compat",
        judge_model: "llama-3.1-8b-instant",
        report_id: "tutor-baseline-20260527-150845",
      },
      authoring: null,
      ingest: null,
    },
  }),
  ok: true,
});

describe("EvalPublicView", () => {
  it("renders the headline and sealed-run-pending banner when nothing promoted", async () => {
    fetchMock.mockResolvedValue(emptySuites());
    renderWithQuery(<EvalPublicView />);
    expect(screen.getByText("Public eval")).toBeInTheDocument();
    expect(
      screen.getByText(/How the tutor scores. Receipts only./i),
    ).toBeInTheDocument();
    // Wait for the query to settle — the empty branch keeps the
    // "no promoted run yet" badge.
    await waitFor(() => {
      expect(screen.getByTestId("eval-sealed-pending")).toBeInTheDocument();
    });
    expect(screen.getByTestId("eval-suites-empty")).toHaveTextContent(
      /No run has been promoted/i,
    );
  });

  it("says it is loading, not that a run is pending, before the query settles", () => {
    // Never resolves: this is the server-rendered / pre-hydration state.
    fetchMock.mockReturnValue(new Promise(() => {}));
    renderWithQuery(<EvalPublicView />);
    expect(screen.getByTestId("eval-sealed-loading")).toHaveTextContent(
      /Loading promoted runs/i,
    );
    expect(screen.getByTestId("eval-suites-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("eval-sealed-pending")).not.toBeInTheDocument();
    expect(screen.queryByText(/pending/i)).not.toBeInTheDocument();
  });

  it("explains the weak scores with their real causes", () => {
    fetchMock.mockResolvedValue(emptySuites());
    renderWithQuery(<EvalPublicView />);
    const banner = screen.getByTestId("eval-honest-numbers-banner");
    expect(banner).toHaveTextContent("[L:L<id>]");
    expect(banner).toHaveTextContent(/label bug/i);
    expect(banner).toHaveTextContent(/noop provider/i);
    expect(banner).toHaveTextContent(/score gate needs a model key/i);
    expect(banner).not.toHaveTextContent(/gated by a CI smoke/i);
  });

  it("says the adversarial probes have not been run", () => {
    fetchMock.mockResolvedValue(emptySuites());
    renderWithQuery(<EvalPublicView />);
    expect(screen.getByText(/nothing sends the probes to the tutor/i)).toBeInTheDocument();
    expect(screen.queryByText(/published with the first sealed run/i)).not.toBeInTheDocument();
  });

  it("renders the canonical worked example with the tool path", () => {
    fetchMock.mockResolvedValue(emptySuites());
    renderWithQuery(<EvalPublicView />);
    expect(
      screen.getByText(/canonical demo question, end-to-end/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Type 'string' is not assignable to type 'T'/i)).toBeInTheDocument();
    expect(screen.getByText("retriever")).toBeInTheDocument();
    expect(screen.getByText("code_runner")).toBeInTheDocument();
  });

  it("renders the methodology link + contact CTA in the footer", () => {
    fetchMock.mockResolvedValue(emptySuites());
    renderWithQuery(<EvalPublicView />);
    expect(
      screen.getByRole("link", { name: /Methodology/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Email me/i })).toHaveAttribute(
      "href",
      expect.stringMatching(/^mailto:ahmedhobeishy@gmail\.com\?/),
    );
  });

  it("renders a SuiteCard with deltas + judge metadata when a suite is promoted", async () => {
    fetchMock.mockResolvedValue(promotedTutor());
    renderWithQuery(<EvalPublicView />);
    // The sealed-run badge flips from "pending" to live.
    await waitFor(() => {
      expect(screen.getByTestId("eval-sealed-live")).toBeInTheDocument();
    });
    // The tutor suite card renders.
    const card = screen.getByTestId("eval-suite-card-tutor");
    expect(card).toHaveTextContent("tutor");
    expect(card).toHaveTextContent("Δ +1.23");
    expect(card).toHaveTextContent("grounding");
    expect(card).toHaveTextContent("+1.50");
    expect(card).toHaveTextContent("accuracy");
    expect(card).toHaveTextContent("+1.00");
    expect(card).toHaveTextContent("n=10");
    expect(card).toHaveTextContent("llama-3.1-8b-instant");
    // An unknown report gets no setup label rather than a wrong one.
    expect(screen.queryByTestId("eval-suite-setup-tutor")).not.toBeInTheDocument();
  });

  it("names the baseline setup of the promoted 2026-05-28 tutor report", async () => {
    fetchMock.mockResolvedValue({
      json: async () => ({
        suites: {
          tutor: {
            suite: "tutor",
            mean_overall: 1.2111,
            axes: { grounding: 3.3333, accuracy: -0.0556, style: 0.3556 },
            items_judged: 9,
            finished_at: "2026-05-28T01:45:45.369081+00:00",
            judge_provider: "openai-compat",
            judge_model: "llama-3.3-70b-versatile",
            report_id: "tutor-baseline-20260528-014421",
          },
          authoring: null,
          ingest: null,
        },
      }),
      ok: true,
    });
    renderWithQuery(<EvalPublicView />);
    const setup = await screen.findByTestId("eval-suite-setup-tutor");
    expect(setup).toHaveTextContent(/vs Mistral Small with no retrieval/i);
    expect(setup).toHaveTextContent(/Llama 3\.3 70B, now retired/i);
    const card = screen.getByTestId("eval-suite-card-tutor");
    expect(card).toHaveTextContent("Δ +1.21");
    expect(card).toHaveTextContent("n=9");
  });

  it("does NOT render fake numbers when no sealed run exists", async () => {
    fetchMock.mockResolvedValue(emptySuites());
    renderWithQuery(<EvalPublicView />);
    await waitFor(() => {
      expect(screen.getByTestId("eval-suites-empty")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Δ \+/)).not.toBeInTheDocument();
    expect(screen.queryByText(/refusal rate: \d+%/i)).not.toBeInTheDocument();
  });
});
