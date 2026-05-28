"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/store";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CeleryTab } from "@/components/admin/observability/CeleryTab";
import { LLMTracesTab } from "@/components/admin/observability/LLMTracesTab";
import { LLMCostTab } from "@/components/admin/observability/LLMCostTab";
import { RateLimitTab } from "@/components/admin/observability/RateLimitTab";
import { RetrievalTab } from "@/components/admin/observability/RetrievalTab";
import { StreamingTab } from "@/components/admin/observability/StreamingTab";
import { useRuntimeFlags } from "@/lib/runtime-flags";

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

type Tab =
  | "celery"
  | "traces"
  | "retrieval"
  | "streaming"
  | "cost"
  | "rate-limit";

const BASE_TABS: { id: Tab; label: string }[] = [
  { id: "celery", label: "Celery" },
  { id: "traces", label: "LLM Traces" },
  { id: "retrieval", label: "Retrieval Quality" },
  // QA-iter3: closes two parity gaps where the backend already
  // shipped operator-visibility endpoints (GET /admin/llm-calls/
  // summary for the 14-day spend rollup, GET /admin/rate-limit-stats
  // for the 429 counts by endpoint) but the admin had to hit the
  // API directly to read them.
  { id: "cost", label: "LLM Cost" },
  { id: "rate-limit", label: "Rate Limits" },
];

// L20.6 — Streaming tab placeholder. Always visible to admins
// (they need to see the wire references + tile placeholders before
// L21 flips); the tile values themselves are the L21 producer's job.
const STREAMING_TAB: { id: Tab; label: string } = {
  id: "streaming",
  label: "Streaming",
};

export default function AdminObservability() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const flags = useRuntimeFlags();
  const [tab, setTab] = useState<Tab>("celery");

  // Admin sees the streaming tab always (for the pre-flip preview);
  // non-admins are already redirected away. The runtime flag still
  // governs whether the tab renders LIVE data vs the placeholder
  // body — both branches are wired below.
  void flags;
  const TABS = [...BASE_TABS, STREAMING_TAB];

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

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList
          className="max-w-full overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
        >
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="celery">
          <CeleryTab />
        </TabsContent>
        <TabsContent value="traces">
          <LLMTracesTab />
        </TabsContent>
        <TabsContent value="retrieval">
          <RetrievalTab />
        </TabsContent>
        <TabsContent value="streaming">
          <StreamingTab />
        </TabsContent>
        <TabsContent value="cost">
          <LLMCostTab />
        </TabsContent>
        <TabsContent value="rate-limit">
          <RateLimitTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
