"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, Play } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api/client";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

/**
 * Admin evals — top-level dashboard.
 *
 * Lumen v2 Phase H2. Three cards (one per suite) with the latest
 * run's mean score, the per-axis breakdown, and a click-through
 * into the suite's history.
 *
 * Visual posture matches the Workbench tokens used across /admin:
 * mono + tabular-nums for every machine value (scores, counts,
 * timestamps), display font for headings, electric-lime only for
 * "click here" hits (not for scores — scores stay foreground so
 * they're legible in both themes).
 *
 * TanStack query keys are hard-coded locally (with the same
 * ``["admin", ...]`` shape the rest of /admin uses) to avoid a
 * conflicting edit to ``lib/query/keys.ts`` while parallel agents
 * are touching it. Lift them into ``keys.ts`` after H2 lands.
 */

type SuiteInfo = {
  name: string;
  item_count: number;
  dataset_path: string;
};

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

export default function AdminEvalsHome() {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin/evals");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  // TODO(H2+1): lift these keys into lib/query/keys.ts once parallel
  // agents stop racing on that file.
  const suitesQ = useQuery({
    queryKey: ["admin", "evals", "suites"],
    queryFn: () => api<SuiteInfo[]>(`/api/v1/admin/evals/suites`),
    enabled: !!user && user.role === "admin",
  });
  const reportsQ = useQuery({
    queryKey: ["admin", "evals", "reports", "all"],
    queryFn: () => api<ReportListItem[]>(`/api/v1/admin/evals/reports`),
    enabled: !!user && user.role === "admin",
  });

  if (!ready || !user || user.role !== "admin") return null;

  const latestBySuite: Record<string, ReportListItem | undefined> = {};
  for (const row of reportsQ.data ?? []) {
    if (!latestBySuite[row.suite]) latestBySuite[row.suite] = row;
  }

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Lumen / admin / evals
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          Eval harness
        </h1>
        <p className="max-w-3xl font-body text-sm text-muted-foreground">
          Golden datasets + LLM-as-judge scoring of the tutor, AI authoring,
          and ingest pipelines. Each suite is graded 0-5 per axis; see a suite
          to drill into past runs and per-item rationales.
        </p>
      </header>

      <RunForm suites={suitesQ.data ?? []} />

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(suitesQ.data ?? []).map((suite) => {
          const latest = latestBySuite[suite.name];
          return (
            <SuiteCard key={suite.name} suite={suite} latest={latest} />
          );
        })}
        {suitesQ.isLoading && (
          <p className="font-mono text-xs text-muted-foreground">Loading suites...</p>
        )}
      </section>
    </div>
  );
}

/**
 * QA-iter3 wires `POST /api/v1/admin/evals/runs` which was shipped
 * without a UI consumer. The endpoint runs synchronously — it can
 * block for tens of seconds (one item × judge_model is ~1-3s for the
 * tutor suite, multiplied by whatever `limit` you pass). The button
 * surfaces a Loader2 spinner + a yellow "may take 30s+" warning so
 * the admin doesn't think the tab hung, and toasts on success with
 * the new report_id. Reports list refetches on success.
 */
function RunForm({ suites }: { suites: SuiteInfo[] }) {
  const qc = useQueryClient();
  const [suite, setSuite] = useState<string>("");
  const [limit, setLimit] = useState<string>("");
  const runMut = useMutation({
    mutationFn: (body: { suite: string; limit?: number }) =>
      api<{
        report_id: string;
        suite: string;
        mean_overall: number | null;
        items_total: number;
      }>("/api/v1/admin/evals/runs", { method: "POST", body }),
    onSuccess: (resp) => {
      toast.success(
        `Run finished — ${resp.report_id} (${resp.items_total} items, mean ${resp.mean_overall?.toFixed(2) ?? "—"})`,
      );
      qc.invalidateQueries({ queryKey: ["admin", "evals"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : "Run failed";
      toast.error(msg);
    },
  });
  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!suite) return;
    const parsed = limit ? Number(limit) : undefined;
    runMut.mutate({
      suite,
      ...(parsed && Number.isFinite(parsed) && parsed > 0
        ? { limit: parsed }
        : {}),
    });
  };
  return (
    <section className="surface mb-8 p-5">
      <h2 className="mb-2 font-display text-lg leading-tight tracking-tight">
        Trigger a new run
      </h2>
      <p className="mb-4 font-body text-sm text-muted-foreground">
        Synchronously executes the selected suite against the configured
        LLM provider + judge. May take 30s+ depending on suite size and
        provider latency. Pass a `limit` for a quick smoke run.
      </p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={onSubmit}
      >
        <div className="min-w-[160px] flex-1">
          <label
            htmlFor="run-suite"
            className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
          >
            Suite
          </label>
          <Select value={suite} onValueChange={setSuite}>
            <SelectTrigger id="run-suite">
              <SelectValue placeholder="Choose a suite" />
            </SelectTrigger>
            <SelectContent>
              {suites.map((s) => (
                <SelectItem key={s.name} value={s.name}>
                  {s.name} ({s.item_count} items)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="min-w-[120px]">
          <label
            htmlFor="run-limit"
            className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
          >
            Limit (optional)
          </label>
          <Input
            id="run-limit"
            type="number"
            min={1}
            max={200}
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="all"
          />
        </div>
        <Button type="submit" disabled={!suite || runMut.isPending}>
          {runMut.isPending ? (
            <>
              <Loader2 className="me-2 h-4 w-4 animate-spin" /> Running…
            </>
          ) : (
            <>
              <Play className="me-2 h-4 w-4" /> Run now
            </>
          )}
        </Button>
      </form>
    </section>
  );
}

function SuiteCard({
  suite,
  latest,
}: {
  suite: SuiteInfo;
  latest: ReportListItem | undefined;
}) {
  return (
    <Link
      href={`/admin/evals/${suite.name}`}
      className="surface group block p-5 transition-colors duration-[160ms] hover:bg-muted/30"
    >
      <div className="mb-3 flex items-center justify-between">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {suite.name}
        </p>
        <ArrowRight className="h-4 w-4 text-muted-foreground transition-colors duration-[160ms] group-hover:text-foreground" />
      </div>
      <div className="mb-4">
        <p className="font-mono text-3xl tabular-nums text-foreground">
          {latest?.mean_overall != null ? latest.mean_overall.toFixed(2) : "—"}
          <span className="ms-2 font-mono text-xs text-muted-foreground">/ 5</span>
        </p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {latest?.items_judged ?? 0} / {suite.item_count} judged
        </p>
      </div>

      <dl className="grid grid-cols-1 gap-1 text-xs">
        {latest && latest.axes ? (
          Object.entries(latest.axes).map(([axis, score]) => (
            <div
              key={axis}
              className="flex items-baseline justify-between gap-3 font-mono text-muted-foreground"
            >
              <dt className="truncate">{axis}</dt>
              <dd className="tabular-nums text-foreground">
                {score.toFixed(2)}
              </dd>
            </div>
          ))
        ) : (
          <p className="font-mono text-xs text-muted-foreground">
            No runs yet — use the "Run now" form above (or
            <span className="text-foreground"> python -m app.evals run --suite {suite.name}</span>
            from the api container).
          </p>
        )}
      </dl>

      {latest?.judge_model && (
        <p className="mt-4 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          judge: {latest.judge_provider}/{latest.judge_model}
        </p>
      )}
    </Link>
  );
}
