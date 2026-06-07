"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

/**
 * Admin evals — per-report item drill-down.
 *
 * Lumen v2 Phase H2. One expandable row per item: shows the
 * golden id, status, per-axis scores, judge rationale, and the
 * full ``actual`` payload (collapsed by default so the table
 * scans cleanly).
 */

type Judge = {
  scores?: Record<string, number>;
  rationale?: string;
  judge_error?: boolean;
};

type ItemRow = {
  id: string;
  suite: string;
  status: string;
  actual?: Record<string, unknown>;
  judge?: Judge;
};

type ReportDetail = {
  report_id: string;
  summary: Record<string, unknown> | null;
  items: ItemRow[];
};

export default function ReportDetailPage() {
  const params = useParams<{ suite: string; reportId: string }>();
  const suite = (params?.suite as string) || "tutor";
  const reportId = (params?.reportId as string) || "";
  const { user, ready } = useAuth();
  const router = useRouter();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!ready) return;
    if (!user)
      router.replace(`/login?next=/admin/evals/${suite}/${reportId}`);
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router, suite, reportId]);

  const reportQ = useQuery({
    queryKey: ["admin", "evals", "report", reportId],
    queryFn: () =>
      api<ReportDetail>(
        `/api/v1/admin/evals/reports/${encodeURIComponent(reportId)}`,
      ),
    enabled: !!user && user.role === "admin" && !!reportId,
  });

  if (!ready || !user || user.role !== "admin") return null;
  if (reportQ.isLoading) {
    return (
      <p className="container mx-auto px-6 py-14 font-mono text-xs text-muted-foreground">
        Loading...
      </p>
    );
  }
  if (reportQ.isError || !reportQ.data) {
    return (
      <p className="container mx-auto px-6 py-14 font-mono text-xs text-muted-foreground">
        Report not found.
      </p>
    );
  }

  const { summary, items } = reportQ.data;
  const meanOverall = (summary?.mean_overall as number | undefined) ?? null;
  const axes = (summary?.axes as Record<string, number> | undefined) ?? {};
  const judgeProvider = summary?.judge_provider as string | undefined;
  const judgeModel = summary?.judge_model as string | undefined;

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <Link
          href={`/admin/evals/${suite}`}
          className="inline-flex items-center gap-1 font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" />
          {suite} history
        </Link>
        <h1 className="font-display text-2xl leading-tight tracking-tight sm:text-3xl">
          {reportId}
        </h1>
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2 font-mono text-xs text-muted-foreground">
          {meanOverall != null && (
            <span>
              mean{" "}
              <span className="tabular-nums text-foreground">
                {meanOverall.toFixed(2)}
              </span>{" "}
              / 5
            </span>
          )}
          {Object.entries(axes).map(([axis, score]) => (
            <span key={axis}>
              {axis}{" "}
              <span className="tabular-nums text-foreground">
                {score.toFixed(2)}
              </span>
            </span>
          ))}
          {judgeModel && (
            <span>
              judge: {judgeProvider}/{judgeModel}
            </span>
          )}
        </div>
      </header>

      <div className="surface overflow-hidden">
        <ul className="divide-y divide-border">
          {items.map((row) => {
            const isOpen = !!expanded[row.id];
            return (
              <li key={row.id} className="px-4 py-3">
                <button
                  type="button"
                  onClick={() =>
                    setExpanded((m) => ({ ...m, [row.id]: !m[row.id] }))
                  }
                  className="flex w-full items-center justify-between gap-4 rounded-sm text-start transition-colors duration-base hover:bg-muted/30"
                >
                  <span className="flex items-center gap-3">
                    {isOpen ? (
                      <ChevronDown className="h-3 w-3 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-3 w-3 text-muted-foreground" />
                    )}
                    <span className="font-mono text-xs text-foreground">
                      {row.id}
                    </span>
                    <StatusBadge status={row.status} judge={row.judge} />
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {row.judge?.scores
                      ? Object.entries(row.judge.scores)
                          .map(([k, v]) => `${k}:${v}`)
                          .join(" · ")
                      : "—"}
                  </span>
                </button>
                {isOpen && (
                  <div className="mt-3 grid grid-cols-1 gap-4 border-t border-border pt-3 md:grid-cols-2">
                    <div>
                      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                        judge rationale
                      </p>
                      <p className="font-body text-sm text-foreground">
                        {row.judge?.rationale || "—"}
                      </p>
                    </div>
                    <div>
                      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                        actual
                      </p>
                      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted/40 p-3 font-mono text-[11px] leading-relaxed text-foreground">
                        {JSON.stringify(row.actual ?? {}, null, 2)}
                      </pre>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
          {!items.length && (
            <li className="px-4 py-12">
              <p className="text-center font-body text-sm text-muted-foreground">
                Report has no items.
              </p>
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  judge,
}: {
  status: string;
  judge: Judge | undefined;
}) {
  const judgeError = judge?.judge_error;
  const label = judgeError ? "judge-error" : status;
  // Loop 14: swapped raw Tailwind hues (amber-700/rose-700) to
  // semantic borders + text colours so this surface respects
  // light-mode tokens.
  const tone =
    status === "ok" && !judgeError
      ? "border-border text-muted-foreground"
      : status === "skipped"
      ? "border-warning/40 text-warning"
      : "border-destructive/40 text-destructive";
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${tone}`}
    >
      {label}
    </span>
  );
}
