"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

/**
 * LLM cost rollup — QA-iter3 wires `/api/v1/admin/llm-calls/summary`,
 * which had been shipped without a UI consumer (caught in the iter-2
 * FE/BE parity audit).
 *
 * Three blocks:
 *   1. Headline totals (calls + cost) over the last 14 days.
 *   2. Cost by feature (tutor.synth, authoring.outline, etc.) —
 *      answers "where is the money going?".
 *   3. Cost by day — answers "is something spiking?".
 *
 * Numbers are rendered with mono+tabular-nums so vertical alignment
 * survives the noop provider's `0.000000` runs alongside future real
 * spend.
 */

type FeatureBucket = { feature: string; calls: number; cost_usd: string };
type DayBucket = { day: string; calls: number; cost_usd: string };
type SummaryOut = {
  total_calls: number;
  total_cost_usd: string;
  by_feature: FeatureBucket[];
  by_day: DayBucket[];
};

function fmtUsd(raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  // 6 fractional digits matches the backend's Decimal precision;
  // collapses trailing zeros so $0.000000 renders as $0 but $0.012345
  // keeps full resolution.
  return `$${n.toFixed(6).replace(/\.?0+$/, "")}`;
}

export function LLMCostTab() {
  const q = useQuery({
    queryKey: ["admin", "observability", "llm-cost"],
    queryFn: () =>
      api<SummaryOut>("/api/v1/admin/llm-calls/summary?days=14"),
    refetchInterval: 60_000,
  });

  if (q.isLoading) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Loading LLM cost summary…
      </p>
    );
  }
  if (q.isError || !q.data) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        LLM cost summary unavailable.
      </p>
    );
  }

  const { total_calls, total_cost_usd, by_feature, by_day } = q.data;

  return (
    <div className="flex flex-col gap-6 pt-4">
      <section className="surface p-4">
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          Last 14 days
        </h2>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="surface p-3">
            <dt className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              Calls
            </dt>
            <dd className="mt-1 font-mono text-xl tabular-nums text-foreground">
              {total_calls.toLocaleString()}
            </dd>
          </div>
          <div className="surface p-3">
            <dt className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              Spend
            </dt>
            <dd className="mt-1 font-mono text-xl tabular-nums text-foreground">
              {fmtUsd(total_cost_usd)}
            </dd>
          </div>
        </dl>
      </section>

      <section className="surface p-4">
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          By feature
        </h2>
        {by_feature.length === 0 ? (
          <p className="font-body text-sm text-muted-foreground">
            No calls in the window.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-2">Feature</th>
                <th className="py-2 text-right">Calls</th>
                <th className="py-2 text-right">Spend</th>
              </tr>
            </thead>
            <tbody>
              {by_feature.map((row) => (
                <tr key={row.feature} className="border-b border-border/40">
                  <td className="py-2 font-mono">{row.feature}</td>
                  <td className="py-2 text-right font-mono tabular-nums">
                    {row.calls.toLocaleString()}
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums">
                    {fmtUsd(row.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="surface p-4">
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          By day
        </h2>
        {by_day.length === 0 ? (
          <p className="font-body text-sm text-muted-foreground">
            No calls in the window.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-2">Day</th>
                <th className="py-2 text-right">Calls</th>
                <th className="py-2 text-right">Spend</th>
              </tr>
            </thead>
            <tbody>
              {by_day.map((row) => (
                <tr key={row.day} className="border-b border-border/40">
                  <td className="py-2 font-mono">{row.day}</td>
                  <td className="py-2 text-right font-mono tabular-nums">
                    {row.calls.toLocaleString()}
                  </td>
                  <td className="py-2 text-right font-mono tabular-nums">
                    {fmtUsd(row.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
