"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

/**
 * Admin audit log — Workbench repaint.
 *
 * Mono for every machine-emitted column: timestamps, action codes,
 * actor IDs, target type:id pairs, JSON data payloads. The action
 * column drops its old lime tint — colour is reserved for hits like
 * Mark Complete; the audit log is reference data, not interactive.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

type AuditEvent = {
  id: string;
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  created_at: string;
  data: Record<string, unknown>;
};

// QA-iter6: resolves `actor_id` opaque IDs in the audit log to a
// human-readable email. `/admin/users?limit=200` already returns the
// admin-visible roster (max 200 rows, ordered by created_at DESC), which
// is plenty for any deployment of Lumen today and avoids the alternative
// (per-event N+1 lookups or a backend join + endpoint contract change).
// The raw ID stays in the cell's `title` attribute so power users can
// still cross-reference.
type UserAdmin = { id: string; email: string; full_name: string | null };

const PAGE_SIZE = 100;

export default function AdminAudit() {
  const t = useT();

  // Cursor for the page currently being fetched. null = head (newest).
  // Each "Load more" click bumps this to the id of the oldest event we
  // currently have, asking the server for events strictly older.
  const [cursor, setCursor] = useState<string | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);

  const pageQ = useQuery({
    queryKey: ["admin", "audit", cursor ?? "head"],
    queryFn: () =>
      api<AuditEvent[]>(
        `/api/v1/admin/audit?limit=${PAGE_SIZE}` +
          (cursor ? `&before=${encodeURIComponent(cursor)}` : ""),
      ),
  });

  const usersQ = useQuery({
    queryKey: ["admin", "audit", "users-for-actor-resolution"],
    queryFn: () => api<UserAdmin[]>(`/api/v1/admin/users?limit=200`),
    staleTime: 60_000,
  });
  const userById = new Map<string, UserAdmin>();
  for (const u of usersQ.data ?? []) userById.set(u.id, u);

  // Append newly-fetched events to the accumulator. Tracked by cursor
  // so we don't re-append on incidental re-renders (TanStack would
  // return the same memoised array reference for unchanged data).
  useEffect(() => {
    if (!pageQ.data) return;
    setEvents((prev) =>
      cursor === null ? pageQ.data! : [...prev, ...pageQ.data!],
    );
  }, [pageQ.data, cursor]);

  const lastFetchedFull = pageQ.data != null && pageQ.data.length === PAGE_SIZE;
  const oldest = events.length ? events[events.length - 1].id : null;

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("adminAudit.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("adminAudit.title")}
        </h1>
      </header>

      <DataTable<AuditEvent>
        ariaLabel={t("adminAudit.title")}
        columns={[
          {
            id: "when",
            header: t("adminAudit.col.when"),
            cell: (e) => (
              <span className="whitespace-nowrap font-mono text-xs tabular-nums text-muted-foreground">
                {new Date(e.created_at).toLocaleString()}
              </span>
            ),
          },
          {
            id: "action",
            header: t("adminAudit.col.action"),
            cell: (e) => <span className="font-mono text-xs text-foreground">{e.action}</span>,
          },
          {
            id: "actor",
            header: t("adminAudit.col.actor"),
            cell: (e) => {
              const u = e.actor_id ? userById.get(e.actor_id) : null;
              return (
                <span
                  className="font-mono text-xs text-muted-foreground"
                  title={e.actor_id ?? undefined}
                >
                  {u ? u.email : (e.actor_id ?? "—")}
                </span>
              );
            },
          },
          {
            id: "target",
            header: t("adminAudit.col.target"),
            cell: (e) => (
              <span className="font-mono text-xs text-muted-foreground">
                {e.target_type ? `${e.target_type}:${e.target_id ?? ""}` : "—"}
              </span>
            ),
          },
          {
            id: "data",
            header: t("adminAudit.col.data"),
            cell: (e) => (
              <span className="font-mono text-xs text-muted-foreground">
                {Object.keys(e.data).length ? JSON.stringify(e.data) : "—"}
              </span>
            ),
          },
        ] as Column<AuditEvent>[]}
        rows={events}
        rowKey={(e) => e.id}
        loading={!events.length && pageQ.isLoading}
        emptyState={
          <p className="font-body text-sm text-muted-foreground">
            {t("adminAudit.empty")}
          </p>
        }
      />
      {lastFetchedFull && oldest && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="outline"
            onClick={() => setCursor(oldest)}
            disabled={pageQ.isFetching}
          >
            {pageQ.isFetching ? t("common.loading") : t("adminAudit.loadOlder")}
          </Button>
        </div>
      )}
    </div>
  );
}
