"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n/provider";

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
    <div className="container mx-auto max-w-5xl px-4 py-14">
      <header className="mb-8 flex flex-col gap-3">
        <Cartouche>{t("adminAudit.cartouche")}</Cartouche>
        <h1 className="font-display text-3xl font-medium tracking-tight">
          {t("adminAudit.title")}
        </h1>
      </header>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminAudit.recentCard")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {/* overflow-x-auto wrapper so the audit table scrolls
              instead of breaking the layout on small viewports. */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gold/15 bg-muted/30 text-start text-[0.65rem] uppercase tracking-[0.28em] text-gold/70">
                <tr>
                  <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.when")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.action")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.actor")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.target")}</th>
                  <th className="px-4 py-3 text-start font-medium">{t("adminAudit.col.data")}</th>
                </tr>
              </thead>
              <tbody className="font-body">
                {events.map((e) => (
                  <tr
                    key={e.id}
                    className="border-t border-border align-top transition-colors hover:bg-muted/20"
                  >
                    <td className="whitespace-nowrap px-4 py-2 text-xs text-muted-foreground">
                      {new Date(e.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-gold/90">{e.action}</td>
                    <td className="px-4 py-2 font-mono text-xs">{e.actor_id ?? "—"}</td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {e.target_type ? `${e.target_type}:${e.target_id ?? ""}` : "—"}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                      {Object.keys(e.data).length ? JSON.stringify(e.data) : "—"}
                    </td>
                  </tr>
                ))}
                {!events.length && !pageQ.isLoading && (
                  <tr>
                    <td colSpan={5} className="px-4 py-12">
                      <div className="flex flex-col items-center gap-3 text-center">
                        <Glyph
                          name="eye"
                          size={40}
                          mode="tint"
                          className="text-gold/40"
                        />
                        <p className="font-body italic text-muted-foreground">
                          {t("adminAudit.empty")}
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
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
