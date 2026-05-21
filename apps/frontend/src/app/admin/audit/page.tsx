"use client";

import { useQuery } from "@tanstack/react-query";
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

export default function AdminAudit() {
  const eventsQ = useQuery({
    queryKey: ["admin", "audit"],
    queryFn: () => api<AuditEvent[]>("/api/v1/admin/audit?limit=200"),
  });

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
              {eventsQ.data?.map((e) => (
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
              {!eventsQ.data?.length && (
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
    </div>
  );
}
