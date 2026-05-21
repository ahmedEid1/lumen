"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";

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
    <div className="container mx-auto max-w-5xl px-4 py-10">
      <h1 className="mb-4 text-2xl font-bold tracking-tight">Audit log</h1>
      <Card>
        <CardHeader>
          <CardTitle>Recent events</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left">
              <tr>
                <th className="px-4 py-2">When</th>
                <th className="px-4 py-2">Action</th>
                <th className="px-4 py-2">Actor</th>
                <th className="px-4 py-2">Target</th>
                <th className="px-4 py-2">Data</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className="border-t align-top">
                  <td className="px-4 py-2 whitespace-nowrap text-xs text-muted-foreground">
                    {new Date(e.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">{e.action}</td>
                  <td className="px-4 py-2 font-mono text-xs">{e.actor_id ?? "—"}</td>
                  <td className="px-4 py-2 font-mono text-xs">
                    {e.target_type ? `${e.target_type}:${e.target_id ?? ""}` : "—"}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">
                    {Object.keys(e.data).length ? JSON.stringify(e.data) : "—"}
                  </td>
                </tr>
              ))}
              {!events.length && !pageQ.isLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                    No events.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {lastFetchedFull && oldest && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="outline"
            onClick={() => setCursor(oldest)}
            disabled={pageQ.isFetching}
          >
            {pageQ.isFetching ? "Loading…" : "Load older events"}
          </Button>
        </div>
      )}
    </div>
  );
}
