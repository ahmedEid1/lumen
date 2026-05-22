"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

/**
 * Admin evals — per-suite history.
 *
 * Lumen v2 Phase H2. Lists every past run of the suite, newest
 * first, with the mean score per axis. Each row links into
 * ``/admin/evals/<suite>/<report_id>`` for the per-item drill-down.
 */

type ReportListItem = {
  report_id: string;
  suite: string;
  started_at: string | null;
  finished_at: string | null;
  mean_overall: number | null;
  axes: Record<string, number>;
  items_total: number | null;
  items_judged: number | null;
  judge_provider: string | null;
  judge_model: string | null;
};

export default function SuiteHistory() {
  const params = useParams<{ suite: string }>();
  const suite = (params?.suite as string) || "tutor";
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace(`/login?next=/admin/evals/${suite}`);
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router, suite]);

  const reportsQ = useQuery({
    queryKey: ["admin", "evals", "reports", suite],
    queryFn: () =>
      api<ReportListItem[]>(
        `/api/v1/admin/evals/reports?suite=${encodeURIComponent(suite)}`,
      ),
    enabled: !!user && user.role === "admin",
  });

  if (!ready || !user || user.role !== "admin") return null;

  const rows = reportsQ.data ?? [];
  const latest = rows[0];
  // Compute the absolute set of axis keys across the runs we're
  // showing so the table header stays stable as older runs drop in.
  const axisNames = Array.from(
    new Set(rows.flatMap((r) => Object.keys(r.axes ?? {}))),
  );

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <Link
          href="/admin/evals"
          className="inline-flex items-center gap-1 font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" />
          all suites
        </Link>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {suite} suite
        </h1>
        {latest?.mean_overall != null && (
          <p className="font-mono text-sm text-muted-foreground">
            latest:{" "}
            <span className="tabular-nums text-foreground">
              {latest.mean_overall.toFixed(2)}
            </span>{" "}
            / 5 ({latest.items_judged ?? 0} judged)
            {latest.judge_model && (
              <span className="ms-3 text-muted-foreground">
                judge: {latest.judge_provider}/{latest.judge_model}
              </span>
            )}
          </p>
        )}
      </header>

      <div className="surface overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-start font-medium">Finished</th>
                <th className="px-4 py-3 text-start font-medium">Run id</th>
                <th className="px-4 py-3 text-end font-medium">Mean</th>
                {axisNames.map((axis) => (
                  <th
                    key={axis}
                    className="px-4 py-3 text-end font-medium normal-case"
                  >
                    {axis}
                  </th>
                ))}
                <th className="px-4 py-3 text-end font-medium">Items</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="font-mono text-xs">
              {rows.map((row) => (
                <tr
                  key={row.report_id}
                  className="border-t border-border align-top transition-colors duration-[160ms] hover:bg-muted/30"
                >
                  <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted-foreground">
                    {row.finished_at
                      ? new Date(row.finished_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-foreground">{row.report_id}</td>
                  <td className="px-4 py-3 text-end tabular-nums text-foreground">
                    {row.mean_overall != null ? row.mean_overall.toFixed(2) : "—"}
                  </td>
                  {axisNames.map((axis) => (
                    <td
                      key={axis}
                      className="px-4 py-3 text-end tabular-nums text-muted-foreground"
                    >
                      {row.axes?.[axis] != null ? row.axes[axis].toFixed(2) : "—"}
                    </td>
                  ))}
                  <td className="px-4 py-3 text-end tabular-nums text-muted-foreground">
                    {row.items_judged ?? 0}/{row.items_total ?? 0}
                  </td>
                  <td className="px-4 py-3 text-end">
                    <Link
                      href={`/admin/evals/${suite}/${row.report_id}`}
                      className="inline-flex items-center gap-1 text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
                    >
                      view
                      <ArrowRight className="h-3 w-3" />
                    </Link>
                  </td>
                </tr>
              ))}
              {!rows.length && !reportsQ.isLoading && (
                <tr>
                  <td colSpan={3 + axisNames.length + 2} className="px-4 py-12">
                    <p className="text-center font-body text-sm text-muted-foreground">
                      No runs yet for this suite.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
