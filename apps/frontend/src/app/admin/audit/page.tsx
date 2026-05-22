"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
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

      <div className="surface overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.when")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.action")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.actor")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.target")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.data")}</th>
              </tr>
            </thead>
            <tbody className="font-mono text-xs">
              {events.map((e) => (
                <tr
                  key={e.id}
                  className="border-t border-border align-top transition-colors duration-[160ms] hover:bg-muted/30"
                >
                  <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted-foreground">
                    {new Date(e.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-foreground">{e.action}</td>
                  <td className="px-4 py-2 text-muted-foreground">{e.actor_id ?? "—"}</td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {e.target_type ? `${e.target_type}:${e.target_id ?? ""}` : "—"}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {Object.keys(e.data).length ? JSON.stringify(e.data) : "—"}
                  </td>
                </tr>
              ))}
              {!events.length && !pageQ.isLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-12">
                    <p className="text-center font-body text-sm text-muted-foreground">
                      {t("adminAudit.empty")}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
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
