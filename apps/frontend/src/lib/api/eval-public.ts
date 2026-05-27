/**
 * `/api/v1/eval/public` consumer (L41-followup).
 *
 * Narrow shape — axes + judge metadata + counts. Per-item answers
 * and judge rationales stay admin-only at /admin/evals/reports.
 *
 * Each suite is `null` when no report has been promoted yet — the
 * public /eval page renders the honest-empty state for that suite.
 */

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query/keys";

export interface PublicSuiteSummary {
  suite: string;
  mean_overall: number | null;
  axes: Record<string, number>;
  items_judged: number | null;
  finished_at: string | null;
  judge_provider: string | null;
  judge_model: string | null;
  report_id: string;
}

export interface PublicEvalResponse {
  suites: Record<string, PublicSuiteSummary | null>;
}

export async function fetchEvalPublic(): Promise<PublicEvalResponse> {
  const res = await fetch("/api/v1/eval/public", {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`GET /api/v1/eval/public failed (${res.status})`);
  }
  return (await res.json()) as PublicEvalResponse;
}

export function useEvalPublic() {
  return useQuery({
    queryKey: qk.evalPublic,
    queryFn: fetchEvalPublic,
    // /eval is a slow-moving public surface — refetch occasionally
    // but don't hammer the endpoint. The promote-eval CLI is the
    // only thing that changes the data, so 5min staleness is fine.
    staleTime: 5 * 60 * 1000,
  });
}
