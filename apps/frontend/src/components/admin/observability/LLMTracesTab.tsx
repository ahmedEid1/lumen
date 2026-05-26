"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api/client";

/**
 * LLM Traces tab — recent metered calls + click-through to trace drill-down.
 *
 * Reads from the existing H1 ``/admin/llm-calls`` endpoint (rather
 * than building a parallel list). Each row links into the trace
 * drill-down at ``/admin/observability/llm-calls/[callId]`` —
 * that page fetches the agent-trace tree + retrieval audits in
 * one round-trip.
 *
 * Visual priority: the cost (USD) and the model are mono+tabular-
 * nums so columns line up. The status column tints error rows.
 */

type LLMCallRow = {
  call_id: string;
  user_id: string;
  feature: string;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string; // serialised as string (Numeric(10,6))
  latency_ms: number;
  status: string;
  error_kind: string | null;
  created_at: string;
};

export function LLMTracesTab() {
  const q = useQuery({
    queryKey: ["admin", "observability", "llm-calls"],
    queryFn: () => api<LLMCallRow[]>("/api/v1/admin/llm-calls?limit=100"),
  });

  if (q.isLoading) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Loading recent LLM calls...
      </p>
    );
  }
  if (q.isError || !q.data) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Could not load LLM call list.
      </p>
    );
  }
  const rows = q.data;
  if (rows.length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        No LLM calls recorded yet.
      </p>
    );
  }

  return (
    <div className="surface overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-4 py-3 text-start font-medium">Time</th>
              <th className="px-4 py-3 text-start font-medium">Call id</th>
              <th className="px-4 py-3 text-start font-medium">Feature</th>
              <th className="px-4 py-3 text-start font-medium">Model</th>
              <th className="px-4 py-3 text-end font-medium">Tokens</th>
              <th className="px-4 py-3 text-end font-medium">Cost ($)</th>
              <th className="px-4 py-3 text-end font-medium">Latency</th>
              <th className="px-4 py-3 text-start font-medium">Status</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="font-mono text-xs">
            {rows.map((row) => (
              <tr
                key={row.call_id}
                className="border-t border-border align-top transition-colors duration-[160ms] hover:bg-muted/30"
              >
                <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted-foreground">
                  {new Date(row.created_at).toLocaleString()}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-foreground">
                  {row.call_id.slice(0, 12)}…
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {row.feature}
                </td>
                <td className="px-4 py-3 text-muted-foreground">{row.model}</td>
                <td className="px-4 py-3 text-end tabular-nums text-foreground">
                  {(row.prompt_tokens + row.completion_tokens).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-end tabular-nums text-foreground">
                  {row.cost_usd}
                </td>
                <td className="px-4 py-3 text-end tabular-nums text-foreground">
                  {row.latency_ms.toLocaleString()} ms
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={row.status} />
                </td>
                <td className="px-4 py-3 text-end">
                  <Link
                    href={`/admin/observability/llm-calls/${row.call_id}`}
                    className="inline-flex items-center gap-1 text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
                  >
                    trace
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  // Loop-5 token cleanup: the throttled tint used to be the raw
  // `bg-yellow-500/15 text-yellow-700 dark:text-yellow-400` which
  // bypassed the Workbench tokens (AUDIT.md §4 #1). Now consumes
  // `--warning` so it reads under both themes.
  const tint =
    status === "error" || status === "budget_exceeded"
      ? "bg-destructive/15 text-destructive"
      : status === "throttled"
      ? "bg-warning/15 text-warning"
      : "text-muted-foreground";
  return <span className={`rounded px-1.5 py-0.5 ${tint}`}>{status}</span>;
}
