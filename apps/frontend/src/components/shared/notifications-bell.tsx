"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={
            unread ? t("notif.ariaWithCount", { n: unread }) : t("nav.notifications.aria")
          }
          className="relative text-muted-foreground hover:text-foreground"
        >
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <span className="absolute end-1.5 top-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[10px] font-semibold tabular-nums text-primary-foreground">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-80 overflow-hidden p-0"
      >
        <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-2">
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("notif.title")}
          </span>
          {unread > 0 && (
            <button
              type="button"
              onClick={() => markAllRead.mutate()}
              disabled={markAllRead.isPending}
              className="font-body text-xs text-muted-foreground transition-colors duration-base hover:text-foreground disabled:opacity-50"
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
                  className={`flex flex-col gap-1 border-b border-border px-3 py-2.5 text-sm last:border-0 transition-colors duration-base ${
                    href ? "cursor-pointer hover:bg-muted/40" : ""
                  } ${!n.read_at ? "bg-muted/30" : ""}`}
                  onClick={() => {
                    if (!n.read_at) markRead.mutate(n.id);
                    if (href) {
                      setOpen(false);
                      router.push(href);
                    }
                  }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <strong className="truncate font-medium text-foreground">{n.title}</strong>
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">
                      {formatRelative(n.created_at)}
                    </span>
                  </div>
                  {n.body && <p className="text-xs text-muted-foreground">{n.body}</p>}
                </li>
              );
            })
          ) : (
            <li className="px-3 py-8 text-center font-body text-sm text-muted-foreground">
              {t("notif.empty")}
            </li>
          )}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
