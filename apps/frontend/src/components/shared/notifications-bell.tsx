"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/query/keys";
import { formatRelative } from "@/lib/utils";

type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
};

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: qk.notifications,
    queryFn: () => api<Notification[]>("/api/v1/me/notifications"),
    refetchInterval: 60_000,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => api(`/api/v1/me/notifications/${id}/read`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.notifications }),
  });

  const markAllRead = useMutation({
    mutationFn: () =>
      api<{ ok: true; marked_read: number }>(
        "/api/v1/me/notifications/read-all",
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.notifications }),
  });

  const unread = (q.data ?? []).filter((n) => !n.read_at).length;

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute right-1.5 top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute right-0 z-40 mt-2 w-80 overflow-hidden rounded-md border bg-card shadow-lg">
            <div className="flex items-center justify-between border-b px-3 py-2 text-sm">
              <span className="font-semibold">Notifications</span>
              {unread > 0 && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    markAllRead.mutate();
                  }}
                  disabled={markAllRead.isPending}
                  className="text-xs text-muted-foreground hover:text-foreground hover:underline disabled:opacity-50"
                >
                  {markAllRead.isPending ? "Marking…" : "Mark all read"}
                </button>
              )}
            </div>
            <ul className="max-h-96 overflow-y-auto">
              {q.data?.length ? (
                q.data.map((n) => (
                  <li
                    key={n.id}
                    className={`flex flex-col gap-1 border-b px-3 py-2 text-sm last:border-0 ${
                      !n.read_at ? "bg-primary/5" : ""
                    }`}
                    onClick={() => !n.read_at && markRead.mutate(n.id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <strong className="truncate">{n.title}</strong>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {formatRelative(n.created_at)}
                      </span>
                    </div>
                    {n.body && <p className="text-muted-foreground">{n.body}</p>}
                  </li>
                ))
              ) : (
                <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                  Nothing here yet.
                </li>
              )}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
