"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

/**
 * Celery health tab — queue depths + worker introspection.
 *
 * The endpoint is best-effort; renders gracefully in three states:
 *
 * - Redis up + worker reachable → queue depths + active/scheduled lists.
 * - Redis up + no worker reachable → queue depths + a "no worker" note.
 * - Redis down → queue rows all zero + an error tag on ``redis_status``.
 *
 * Refetches every 10s — short enough to catch a wedge fast, long
 * enough not to spam the API.
 */

type CeleryQueue = { name: string; depth: number };

type CeleryHealth = {
  redis_status: string;
  queues: CeleryQueue[];
  active: Record<string, Array<Record<string, unknown>>> | null;
  scheduled: Record<string, Array<Record<string, unknown>>> | null;
  note: string | null;
};

export function CeleryTab() {
  const q = useQuery({
    queryKey: ["admin", "observability", "celery"],
    queryFn: () => api<CeleryHealth>("/api/v1/admin/observability/celery"),
    refetchInterval: 10_000,
  });

  if (q.isLoading) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Loading Celery health...
      </p>
    );
  }
  if (q.isError || !q.data) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        Celery health unavailable.
      </p>
    );
  }

  const data = q.data;
  const isRedisOk = data.redis_status === "ok";

  return (
    <div className="flex flex-col gap-8">
      <section>
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          Broker
        </h2>
        <p className="font-mono text-xs text-muted-foreground">
          redis_status:{" "}
          <span
            className={
              isRedisOk
                ? "text-foreground"
                : "rounded bg-destructive/15 px-1.5 py-0.5 text-destructive"
            }
          >
            {data.redis_status}
          </span>
        </p>
        {data.note && (
          <p className="mt-2 font-mono text-xs text-muted-foreground">
            note: <span className="text-foreground">{data.note}</span>
          </p>
        )}
      </section>

      <section>
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          Queue depths
        </h2>
        <div className="surface overflow-hidden">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-start font-medium">Queue</th>
                <th className="px-4 py-3 text-end font-medium">Depth</th>
              </tr>
            </thead>
            <tbody className="font-mono text-xs">
              {data.queues.map((q) => (
                <tr key={q.name} className="border-t border-border">
                  <td className="px-4 py-3 text-foreground">{q.name}</td>
                  <td className="px-4 py-3 text-end tabular-nums text-foreground">
                    {q.depth.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 font-display text-lg leading-tight tracking-tight">
          Workers
        </h2>
        <WorkerSection title="Active" workers={data.active} />
        <WorkerSection title="Scheduled" workers={data.scheduled} />
      </section>
    </div>
  );
}

function WorkerSection({
  title,
  workers,
}: {
  title: string;
  workers: Record<string, Array<Record<string, unknown>>> | null;
}) {
  if (workers === null) {
    return (
      <p className="mb-4 font-mono text-xs text-muted-foreground">
        {title}: <span className="text-foreground">no data</span>
      </p>
    );
  }
  const entries = Object.entries(workers);
  if (entries.length === 0) {
    return (
      <p className="mb-4 font-mono text-xs text-muted-foreground">
        {title}: <span className="text-foreground">none</span>
      </p>
    );
  }
  return (
    <div className="mb-4">
      <p className="mb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      <ul className="font-mono text-xs">
        {entries.map(([worker, tasks]) => (
          <li key={worker} className="border-t border-border px-1 py-2">
            <span className="text-foreground">{worker}</span>{" "}
            <span className="text-muted-foreground">
              ({tasks.length} task{tasks.length === 1 ? "" : "s"})
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
