"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

/**
 * Rate-limit observability — QA-iter3 wires
 * `/api/v1/admin/rate-limit-stats`, which had been shipped without a
 * UI consumer (caught in the iter-2 FE/BE parity audit).
 *
 * Displays the total number of 429s in the rolling window (default
 * 1 hour) and the breakdown by endpoint. Useful for:
 *  - confirming that a user-reported 429 actually fired
 *  - spotting attack patterns (one IP hammering one endpoint)
 *  - tuning rate-limit caps (if the most-throttled endpoint is
 *    something legitimate users hit hard, the cap is too tight)
 */

type RateLimitStats = {
  since: number;
  window_seconds: number;
  total: number;
  by_endpoint: Record<string, number>;
};

function fmtWindow(seconds: number): string {
  if (seconds >= 3600) {
    const hrs = seconds / 3600;
    return `${hrs.toFixed(hrs % 1 === 0 ? 0 : 1)} h`;
  }
  if (seconds >= 60) return `${(seconds / 60).toFixed(0)} m`;
  return `${seconds.toFixed(0)} s`;
}

export function RateLimitTab() {
  const q = useQuery({
    queryKey: ["admin", "observability", "rate-limit"],
    queryFn: () =>
      api<RateLimitStats>("/api/v1/admin/rate-limit-stats"),
    refetchInterval: 30_000,
  });

  if (q.isLoading) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Loading rate-limit stats…
      </p>
    );
  }
  if (q.isError || !q.data) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Rate-limit stats unavailable.
      </p>
    );
  }

  const { window_seconds, total, by_endpoint } = q.data;
  const rows = Object.entries(by_endpoint).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex flex-col gap-6 pt-4">
      <section className="surface p-4">
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          429s in the last {fmtWindow(window_seconds)}
        </h2>
        <p className="font-mono text-3xl tabular-nums text-foreground">
          {total.toLocaleString()}
        </p>
        <p className="mt-2 font-body text-xs text-muted-foreground">
          Counts come from{" "}
          <span className="font-mono">app.core.rate_limit_metrics</span>{" "}
          (in-memory Redis sorted-set with timestamp scoring). A
          Prometheus exporter on the next deploy would pin this same
          number.
        </p>
      </section>

      <section className="surface p-4">
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          By endpoint
        </h2>
        {rows.length === 0 ? (
          <p className="font-body text-sm text-muted-foreground">
            No 429s in the window — limits are not biting.
          </p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-2">Endpoint</th>
                <th className="py-2 text-right">429 count</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([endpoint, count]) => (
                <tr key={endpoint} className="border-b border-border/40">
                  <td className="py-2 font-mono">{endpoint}</td>
                  <td className="py-2 text-right font-mono tabular-nums">
                    {count.toLocaleString()}
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
