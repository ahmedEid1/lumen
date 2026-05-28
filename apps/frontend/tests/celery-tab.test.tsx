import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CeleryTab } from "@/components/admin/observability/CeleryTab";
import * as apiClient from "@/lib/api/client";

// Regression cover for the iter-24b relabel: the Workers panel renders Celery
// inspect.active()/scheduled() TASK lists, not a roster of online workers, so
// the headings and empty/null states must read as task activity (an
// online-but-idle worker must not look like "no workers").

type CeleryHealth = {
  redis_status: string;
  queues: { name: string; depth: number }[];
  active: Record<string, unknown[]> | null;
  scheduled: Record<string, unknown[]> | null;
  note: string | null;
};

const base: CeleryHealth = {
  redis_status: "ok",
  queues: [{ name: "default", depth: 3 }],
  active: {},
  scheduled: {},
  note: null,
};

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("CeleryTab — Workers panel", () => {
  let apiSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    apiSpy = vi.spyOn(apiClient, "api");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("labels the sections as task lists, not a worker roster", async () => {
    apiSpy.mockResolvedValueOnce(base as never);
    renderWithClient(<CeleryTab />);

    expect(await screen.findByText(/Active tasks:/)).toBeInTheDocument();
    expect(screen.getByText(/Scheduled tasks:/)).toBeInTheDocument();
    // The clarifier disambiguates task activity from worker liveness.
    expect(screen.getByText(/not a roster of online workers/i)).toBeInTheDocument();
    // Bare "Active"/"Scheduled" headings must be gone (the mislabel).
    expect(screen.queryByText("Active:")).not.toBeInTheDocument();
    expect(screen.queryByText("Scheduled:")).not.toBeInTheDocument();
  });

  it("shows 'none reported' for an empty task dict (reachable, idle)", async () => {
    apiSpy.mockResolvedValueOnce(base as never);
    renderWithClient(<CeleryTab />);
    // active + scheduled both {} → both say "none reported".
    expect(await screen.findAllByText("none reported")).toHaveLength(2);
  });

  it("shows 'no worker reachable' when inspect returned null", async () => {
    apiSpy.mockResolvedValueOnce({
      ...base,
      active: null,
      scheduled: null,
      note: "no worker reachable within 2s",
    } as never);
    renderWithClient(<CeleryTab />);
    expect(await screen.findAllByText("no worker reachable")).toHaveLength(2);
    // The broker note still surfaces the underlying reason.
    expect(screen.getByText(/no worker reachable within 2s/i)).toBeInTheDocument();
  });

  it("lists workers with their task counts when reachable", async () => {
    apiSpy.mockResolvedValueOnce({
      ...base,
      active: { "celery@host-1": [{ id: "t1" }] },
      scheduled: {},
    } as never);
    renderWithClient(<CeleryTab />);
    expect(await screen.findByText("celery@host-1")).toBeInTheDocument();
    expect(screen.getByText(/\(1 task\)/)).toBeInTheDocument();
  });
});
