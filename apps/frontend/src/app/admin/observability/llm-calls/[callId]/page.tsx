"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { TraceTree, type TraceStep } from "@/components/admin/observability/TraceTree";

/**
 * LLM call drill-down — call summary + trace tree + retrieval audits.
 *
 * Lumen v2 Phase H7. Fetches the nested ``{call, traces, audits}``
 * payload in one round-trip and renders three stacked sections:
 *
 * 1. **Call summary** — feature, model, tokens, cost, latency,
 *    status. Mono+tabular-nums for every machine value.
 * 2. **Agent trace** — the collapsible tree of steps the agent(s)
 *    took to produce this call's output. Renders an empty state
 *    when no steps were recorded (the steady state until I2 ships).
 * 3. **Retrieval audits** — any RAG retrievals that happened just
 *    before this call (temporal heuristic on the backend). The
 *    full chunk list with similarity scores.
 */

type LLMCallSummary = {
  call_id: string;
  user_id: string;
  feature: string;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: string;
  latency_ms: number;
  status: string;
  error_kind: string | null;
  created_at: string;
};

type RetrievalAudit = {
  audit_id: string;
  user_id: string;
  feature: string;
  query: string;
  course_id: string | null;
  chunks: Array<{
    chunk_id: string;
    lesson_id: string;
    score: number;
    snippet: string;
  }>;
  top_score: number | null;
  created_at: string;
};

type CallTracePayload = {
  call: LLMCallSummary;
  traces: TraceStep[];
  audits: RetrievalAudit[];
};

export default function LLMCallTracePage() {
  const params = useParams<{ callId: string }>();
  const callId = (params?.callId as string) ?? "";
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    if (!user)
      router.replace(`/login?next=/admin/observability/llm-calls/${callId}`);
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router, callId]);

  const q = useQuery({
    queryKey: ["admin", "observability", "llm-call", callId],
    queryFn: () =>
      api<CallTracePayload>(
        `/api/v1/admin/observability/llm-calls/${encodeURIComponent(callId)}/trace`,
      ),
    enabled: !!user && user.role === "admin" && !!callId,
  });

  if (!ready || !user || user.role !== "admin") return null;

  return (
    <div className="container mx-auto max-w-5xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <Link
          href="/admin/observability"
          className="inline-flex items-center gap-1 font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" />
          observability
        </Link>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          Call trace
        </h1>
        <p className="font-mono text-xs text-muted-foreground">
          call_id: <span className="text-foreground">{callId}</span>
        </p>
      </header>

      {q.isLoading && (
        <p className="font-mono text-xs text-muted-foreground">Loading...</p>
      )}
      {q.isError && (
        <p className="font-mono text-xs text-destructive">
          Could not load trace.{" "}
          {q.error instanceof Error ? q.error.message : ""}
        </p>
      )}

      {q.data && (
        <div className="flex flex-col gap-10">
          <CallSummarySection call={q.data.call} />
          <section>
            <h2 className="mb-4 font-display text-lg leading-tight tracking-tight">
              Agent trace
            </h2>
            <div className="surface p-4">
              <TraceTree steps={q.data.traces} />
            </div>
          </section>
          <section>
            <h2 className="mb-4 font-display text-lg leading-tight tracking-tight">
              Retrieval audits
            </h2>
            {q.data.audits.length === 0 ? (
              <p className="font-mono text-xs text-muted-foreground">
                No retrieval audits linked to this call.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {q.data.audits.map((a) => (
                  <AuditCard key={a.audit_id} audit={a} />
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function CallSummarySection({ call }: { call: LLMCallSummary }) {
  return (
    <section>
      <h2 className="mb-4 font-display text-lg leading-tight tracking-tight">
        Call
      </h2>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="feature" value={call.feature} />
        <Field label="provider" value={call.provider} />
        <Field label="model" value={call.model} />
        <Field label="status" value={call.status} />
        <Field
          label="tokens"
          value={(call.prompt_tokens + call.completion_tokens).toLocaleString()}
        />
        <Field label="cost ($)" value={call.cost_usd} />
        <Field
          label="latency"
          value={`${call.latency_ms.toLocaleString()} ms`}
        />
        <Field
          label="at"
          value={new Date(call.created_at).toLocaleString()}
        />
      </dl>
      {call.error_kind && (
        <p className="mt-3 font-mono text-xs text-destructive">
          error_kind: <span>{call.error_kind}</span>
        </p>
      )}
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface p-3">
      <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 break-all font-mono text-sm tabular-nums text-foreground">
        {value}
      </dd>
    </div>
  );
}

function AuditCard({ audit }: { audit: RetrievalAudit }) {
  return (
    <li className="surface p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex flex-col gap-1">
          <p className="font-display text-base leading-tight tracking-tight text-foreground">
            {audit.query}
          </p>
          <p className="font-mono text-xs text-muted-foreground">
            {new Date(audit.created_at).toLocaleString()}
            {audit.course_id && (
              <>
                {" · "}course:{" "}
                <span className="text-foreground">{audit.course_id}</span>
              </>
            )}
          </p>
        </div>
        {audit.top_score !== null && (
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs tabular-nums text-foreground">
            top: {audit.top_score.toFixed(3)}
          </span>
        )}
      </div>
      <ol className="flex flex-col gap-2">
        {audit.chunks.map((c, i) => (
          <li
            key={c.chunk_id}
            className="flex items-baseline gap-3 border-l-2 border-border pl-3"
          >
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              #{i + 1}
            </span>
            <div className="flex-1">
              <p className="font-mono text-xs text-foreground">
                {c.snippet}
                {c.snippet.length >= 120 && (
                  <span className="text-muted-foreground">…</span>
                )}
              </p>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                chunk {c.chunk_id.slice(0, 10)} · score{" "}
                <span className="tabular-nums text-foreground">
                  {c.score.toFixed(3)}
                </span>
              </p>
            </div>
          </li>
        ))}
      </ol>
    </li>
  );
}
