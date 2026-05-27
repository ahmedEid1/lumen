"use client";

import { Activity, Clock, Network, WifiOff } from "lucide-react";

/**
 * L20.6 — Streaming observability tile placeholders.
 *
 * The L21 streaming-tutor stack will emit per-turn metrics into Redis
 * + the `tutor_turn_jobs` table. This tab is the consumer surface;
 * the tiles below render with no-data placeholders until L21a lands
 * the producer side.
 *
 * Layout matches the rest of /admin/observability — surface-1
 * bordered card per tile, mono+tabular-nums for every machine value,
 * EmptyState body text describing what each tile will mean once data
 * flows. The tab visibility itself is gated on
 * `flags.tutor_streaming` so it stays hidden in prod until L21b
 * flips the runtime-flag default.
 */

interface TileProps {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
  value: string;
  helper: string;
}

function Tile({ icon: Icon, label, value, helper }: TileProps) {
  return (
    <div className="surface flex flex-col gap-3 p-5">
      <div className="flex items-center justify-between">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <Icon aria-hidden className="h-4 w-4 text-muted-foreground/60" />
      </div>
      <p className="font-display text-3xl tabular-nums leading-none">
        {value}
      </p>
      <p className="font-body text-xs text-muted-foreground">{helper}</p>
    </div>
  );
}

export function StreamingTab() {
  return (
    <div className="space-y-6 pt-4">
      <div className="surface border-dashed border-border bg-muted/20 p-4">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Pre-flip preview
        </p>
        <p className="mt-1 font-body text-sm">
          The tiles below are placeholders. Live values land with the
          L21a streaming-tutor producer (Celery task + Redis Streams)
          and become visible to non-admins once L21b flips
          <code className="mx-1 rounded bg-muted/50 px-1 py-0.5 font-mono text-xs">
            feature_tutor_streaming
          </code>
          on.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          icon={Clock}
          label="First-token p50"
          value="—"
          helper="Median time to first SSE token across the last 5 minutes of turns."
        />
        <Tile
          icon={Clock}
          label="First-token p95"
          value="—"
          helper="95th percentile — the long-tail tells you whether the planner is starving."
        />
        <Tile
          icon={Activity}
          label="Active streams"
          value="—"
          helper="In-flight turns right now. Cap is 4 / Celery worker; multiplies by replica count."
        />
        <Tile
          icon={WifiOff}
          label="Disconnect rate"
          value="—"
          helper="Streams that ended before turn_complete. Includes Last-Event-ID resumes."
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Tile
          icon={Clock}
          label="Total turn latency p50"
          value="—"
          helper="Median end-to-end. Includes planning + retrieval + tool calls + synthesis."
        />
        <Tile
          icon={Network}
          label="Tool-mix breakdown"
          value="—"
          helper="Fraction of turns that fired each sub-agent. Sanity-checks the planner."
        />
      </div>

      <div className="surface space-y-3 p-5">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Wire references
        </p>
        <ul className="space-y-1 font-body text-sm text-muted-foreground">
          <li>
            <code className="font-mono text-xs text-foreground">
              ADR-0017
            </code>{" "}
            — Celery worker pool (4 prefork children;{" "}
            <code className="font-mono text-xs">asyncio.run()</code> per task).
          </li>
          <li>
            <code className="font-mono text-xs text-foreground">
              ADR-0018
            </code>{" "}
            — Redis Streams (
            <code className="font-mono text-xs">XADD</code>/
            <code className="font-mono text-xs">XREAD</code>) over pub/sub for
            SSE replay.
          </li>
          <li>
            <code className="font-mono text-xs text-foreground">
              ADR-0019
            </code>{" "}
            — Atomic phase fence +{" "}
            <code className="font-mono text-xs">after_commit</code> enqueue.
          </li>
        </ul>
      </div>
    </div>
  );
}
