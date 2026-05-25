"use client";

import { use, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Traces } from "@/lib/api/endpoints";
import { useAuth } from "@/lib/auth/store";
import { CostBadge } from "@/components/trace/CostBadge";
import { TraceTimeline } from "@/components/trace/TraceTimeline";
import { RetrievalChunkList } from "@/components/trace/RetrievalChunkList";

/**
 * Learner-facing tutor turn drill-down (Lumen v2 Phase I4).
 *
 * The "show me how you got this" full-page view. From any
 * assistant message in a tutor conversation the learner can
 * land here and see:
 *
 *   - top-of-page CostBadge with total cost / latency / tokens
 *     / confidence — the technical-credibility flex
 *   - a vertical TraceTimeline of every step the orchestrator
 *     emitted (plan → tool_calls → optional re-plan → synthesis)
 *   - the retrieval audits that fed the answer, with similarity
 *     scores in mono + tabular-nums
 *
 * Implemented as a client component to match the dashboard's
 * existing data-fetching pattern (TanStack Query + cookie auth).
 * The backend endpoint enforces ownership (403 on stranger
 * conversations) — this page's role is the UX shell + the
 * client-side redirect guard.
 */

export default function TutorTurnTracePage({
  params,
}: {
  params: Promise<{ conversationId: string; messageId: string }>;
}) {
  const { conversationId, messageId } = use(params);
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      router.replace(
        `/login?next=/dashboard/tutor/${conversationId}/turn/${messageId}`,
      );
    }
  }, [ready, user, router, conversationId, messageId]);

  const traceQ = useQuery({
    queryKey: ["tutor-turn-trace", conversationId, messageId],
    queryFn: () => Traces.tutorTurn(conversationId, messageId),
    enabled: !!user,
  });

  if (!ready || !user) return null;

  if (traceQ.isLoading) {
    return (
      <div className="container mx-auto px-6 py-14">
        <p className="font-mono text-xs text-muted-foreground">
          Loading trace...
        </p>
      </div>
    );
  }

  if (traceQ.isError || !traceQ.data) {
    return (
      <div className="container mx-auto px-6 py-14">
        <div className="surface flex flex-col items-start gap-3 p-6">
          <p className="font-display text-base leading-tight">
            Could not load the trace.
          </p>
          <p className="font-body text-sm text-muted-foreground">
            {traceQ.error instanceof Error
              ? traceQ.error.message
              : "Unknown error."}
          </p>
          <Link href="/dashboard">
            <Button variant="outline" size="sm">
              <ArrowLeft className="me-2 h-4 w-4" /> Back to dashboard
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  const data = traceQ.data;
  const totalTokens =
    (data.total_prompt_tokens ?? 0) + (data.total_completion_tokens ?? 0);

  return (
    <div className="container mx-auto flex max-w-5xl flex-col gap-8 px-6 py-14">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Link href="/dashboard">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="me-2 h-4 w-4" /> Back to dashboard
            </Button>
          </Link>
        </div>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Show me how you got this
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          Tutor turn trace
        </h1>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">
          conversation {data.conversation_id} · message {data.message_id} ·{" "}
          {data.agent_traces.length} step
          {data.agent_traces.length === 1 ? "" : "s"}
        </p>
      </header>

      <CostBadge
        costUsd={data.total_cost_usd}
        latencyMs={data.total_latency_ms}
        totalTokens={totalTokens}
        confidence={data.confidence}
        stepCount={data.agent_traces.length}
      />

      {data.llm_call ? (
        <section className="surface flex flex-col gap-2 p-4">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Underlying LLM call
          </p>
          <div className="flex flex-wrap items-baseline gap-3 font-mono text-sm tabular-nums">
            <span className="text-primary">{data.llm_call.feature}</span>
            <span className="text-muted-foreground">·</span>
            <span>
              {data.llm_call.provider}/{data.llm_call.model}
            </span>
            <span className="text-muted-foreground">·</span>
            <span>{data.llm_call.prompt_tokens} prompt</span>
            <span className="text-muted-foreground">·</span>
            <span>{data.llm_call.completion_tokens} completion</span>
            <span className="text-muted-foreground">·</span>
            <span>{data.llm_call.latency_ms}ms</span>
          </div>
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Step-by-step
        </h2>
        <TraceTimeline
          steps={data.agent_traces}
          emptyLabel="No trace recorded for this turn. The orchestrator may not have run (refused or empty-retrieval turn)."
        />
      </section>

      {data.retrieval_audits.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h2 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Retrieval audits ({data.retrieval_audits.length})
          </h2>
          <div className="flex flex-col gap-4">
            {data.retrieval_audits.map((audit) => (
              <article
                key={audit.audit_id}
                className="surface flex flex-col gap-2 p-4"
                data-testid="retrieval-audit-card"
              >
                <div className="flex flex-wrap items-baseline gap-2 font-mono text-xs text-muted-foreground">
                  <span className="text-primary">{audit.feature}</span>
                  <span>·</span>
                  <span className="text-foreground/70">
                    &quot;{audit.query}&quot;
                  </span>
                  {audit.top_score !== null ? (
                    <>
                      <span>·</span>
                      <span className="tabular-nums">
                        top score {audit.top_score.toFixed(3)}
                      </span>
                    </>
                  ) : null}
                </div>
                <RetrievalChunkList chunks={audit.chunks as never} />
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
