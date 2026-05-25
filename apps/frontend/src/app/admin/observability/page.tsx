"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/store";
import { CeleryTab } from "@/components/admin/observability/CeleryTab";
import { LLMTracesTab } from "@/components/admin/observability/LLMTracesTab";
import { RetrievalTab } from "@/components/admin/observability/RetrievalTab";

/**
 * Admin observability — three-tab dashboard.
 *
 * Lumen v2 Phase H7. The surface I2 (multi-agent tutor) and I3
 * (self-critique authoring) write traces into. Today the dashboard
 * renders an empty trace tree for most LLM calls because no agent
 * has been refactored to emit steps yet; the substrate is in
 * place so the UI lights up automatically as I2/I3 land.
 *
 * Tabs:
 *
 * 1. **Celery** — broker queue depths + worker introspection. The
 *    health-at-a-glance view; a long queue depth is the
 *    cheapest "something is wedged" signal.
 * 2. **LLM Traces** — recent metered LLM calls (already shown in
 *    /admin/llm-calls from H1), now click-through to a trace
 *    drill-down at /admin/observability/llm-calls/[callId].
 * 3. **Retrieval Quality** — the RAG retriever's audit log: query,
 *    course, top-K chunks with similarity scores.
 *
 * Visual posture matches the Workbench tokens used across /admin:
 * mono + tabular-nums for every machine value (IDs, scores,
 * latencies, queue depths); display font for headings; tabs are a
 * single row of bordered buttons that doubles as a left-rail.
 */

type Tab = "celery" | "traces" | "retrieval";

const TABS: { id: Tab; label: string }[] = [
  { id: "celery", label: "Celery" },
  { id: "traces", label: "LLM Traces" },
  { id: "retrieval", label: "Retrieval Quality" },
];

export default function AdminObservability() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("celery");

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/admin/observability");
    else if (user.role !== "admin") router.replace("/dashboard");
  }, [ready, user, router]);

  if (!ready || !user || user.role !== "admin") return null;

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Lumen / admin / observability
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          Observability
        </h1>
        <p className="max-w-3xl font-body text-sm text-muted-foreground">
          Queue depths, agent traces, and retrieval quality. The
          trace substrate is shared by every agentic flow — the
          multi-agent tutor and self-critique authoring write
          steps into the same table you see here.
        </p>
      </header>

      <nav className="mb-8 flex flex-wrap items-center gap-2 border-b border-border pb-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            aria-selected={tab === t.id}
            className={
              "px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition-colors duration-[160ms]" +
              (tab === t.id
                ? " border-b-2 border-foreground text-foreground"
                : " border-b-2 border-transparent text-muted-foreground hover:text-foreground")
            }
          >
            {t.label}
          </button>
        ))}
      </nav>

      <section role="tabpanel" aria-label={`Observability: ${tab}`}>
        {tab === "celery" && <CeleryTab />}
        {tab === "traces" && <LLMTracesTab />}
        {tab === "retrieval" && <RetrievalTab />}
      </section>
    </div>
  );
}
