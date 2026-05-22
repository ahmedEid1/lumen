"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/query/keys";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
};

/** Map a notification to a deep-link URL using its kind + data payload. */
function targetHref(n: Notification): string | null {
  const d = n.data || {};
  switch (n.kind) {
    case "enrolled":
    case "lesson_available":
      return d.course_id ? `/courses/${d.course_id}` : null;
    case "certificate_ready":
      return d.course_id ? `/courses/${d.course_id}` : null;
    case "review_received":
      return d.course_id
        ? `/courses/${d.course_id}#reviews`
        : null;
    case "discussion_reply":
      return d.discussion_id && d.course_id
        ? `/courses/${d.course_id}/discussions/${d.discussion_id}`
        : null;
    default:
      return null;
  }
}

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const router = useRouter();
  const t = useT();
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
        aria-label={
          unread ? t("notif.ariaWithCount", { n: unread }) : t("nav.notifications.aria")
        }
        onClick={() => setOpen((v) => !v)}
        className="text-gold/80 hover:text-gold"
      >
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute end-1.5 top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute end-0 z-40 mt-2 w-80 overflow-hidden rounded-md border border-gold/20 bg-card shadow-lg scroll-paper">
            <div className="flex items-center justify-between border-b border-gold/15 px-3 py-2 text-sm">
              <span className="font-display text-base font-medium text-gold/90">
                {t("notif.title")}
              </span>
              {unread > 0 && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    markAllRead.mutate();
                  }}
                  disabled={markAllRead.isPending}
                  className="font-body text-xs text-muted-foreground transition-colors hover:text-gold hover:underline disabled:opacity-50"
                >
                  {markAllRead.isPending ? t("notif.marking") : t("notif.markAllRead")}
                </button>
              )}
            </div>
            <ul className="max-h-96 overflow-y-auto font-body">
              {q.data?.length ? (
                q.data.map((n) => {
                  const href = targetHref(n);
                  return (
                    <li
                      key={n.id}
                      className={`flex flex-col gap-1 border-b border-gold/10 px-3 py-2 text-sm last:border-0 ${
                        href ? "cursor-pointer hover:bg-muted/40" : ""
                      } ${!n.read_at ? "bg-gold/5" : ""}`}
                      onClick={() => {
                        if (!n.read_at) markRead.mutate(n.id);
                        if (href) {
                          setOpen(false);
                          router.push(href);
                        }
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <strong className="truncate text-foreground">{n.title}</strong>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {formatRelative(n.created_at)}
                        </span>
                      </div>
                      {n.body && <p className="text-muted-foreground">{n.body}</p>}
                    </li>
                  );
                })
              ) : (
                <li className="px-3 py-6 text-center text-sm italic text-muted-foreground">
                  {t("notif.empty")}
                </li>
              )}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
