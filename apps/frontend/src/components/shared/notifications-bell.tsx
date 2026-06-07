"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { api, ApiError } from "@/lib/api/client";
import { Me } from "@/lib/api/endpoints";
import { type NotificationItem } from "@/lib/notifications";
import {
  NotificationRow,
  useNotificationActions,
} from "@/components/shared/notification-row";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

// Mirrors the backend cap in notifications_repo.list_for_user (limit=50).
// The popover shows the newest 50; everything older is reachable on the
// /notifications inbox page (cursor-paged), linked from the footer.
const NOTIF_CAP = 50;

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const router = useRouter();
  const t = useT();
  const { user } = useAuth();
  // The bell only mounts for a signed-in user, but the session can lapse
  // while it stays mounted (the access cookie expires; the auth store's
  // `user` hasn't been refreshed yet). Without a brake the 60s poller then
  // hammers the API with 401s forever. So: tie polling to the auth-state
  // signal the rest of the app uses (`user`), and once a 401 is observed,
  // freeze the poller until the auth identity changes again. `user?.id` is
  // the dependency — a fresh login (or account switch) flips it and re-arms
  // the query; a plain re-render does not.
  const userId = user?.id ?? null;

  // Badge: ONE cheap COUNT every 60s — accurate past the 50-row list cap
  // and far lighter than hydrating 50 full rows per tick (the pre-batch
  // behaviour). Cache scoped to the identity so a fresh login gets a clean
  // entry instead of inheriting a stuck 401.
  const countQ = useQuery({
    queryKey: [...qk.notificationsCount, userId],
    queryFn: () => Me.notificationUnreadCount(),
    enabled: !!userId,
    refetchInterval: (query) =>
      query.state.error instanceof ApiError && query.state.error.status === 401
        ? false
        : 60_000,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 401 ? false : failureCount < 2,
  });

  // The full list is only fetched while the popover is open — the badge no
  // longer depends on it. The notification mutations invalidate by the
  // `qk.notifications` prefix, which matches this longer key.
  const listQ = useQuery({
    queryKey: [...qk.notifications, userId],
    queryFn: () => api<NotificationItem[]>("/api/v1/me/notifications"),
    enabled: !!userId && open,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 401 ? false : failureCount < 2,
  });

  const actions = useNotificationActions(userId);

  const unread = countQ.data?.unread_count ?? 0;
  const items = listQ.data ?? [];
  const readCount = items.filter((n) => n.read_at).length;
  const atCap = items.length >= NOTIF_CAP;

  // Polite SR announcement when new notifications arrive between polls.
  // Diffed against the previous count (never announces on first load), so
  // a steady poll stays silent.
  const prevUnread = useRef<number | null>(null);
  const [announce, setAnnounce] = useState("");
  useEffect(() => {
    if (countQ.data == null) return;
    const current = countQ.data.unread_count;
    if (prevUnread.current !== null && current > prevUnread.current) {
      setAnnounce(t("notif.newAnnounce", { n: current - prevUnread.current }));
    }
    prevUnread.current = current;
  }, [countQ.data, t]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <span aria-live="polite" aria-atomic="true" className="sr-only">
        {announce}
      </span>
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
      <PopoverContent align="end" className="w-80 overflow-hidden p-0">
        <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/40 px-3 py-2">
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("notif.title")}
          </span>
          <span className="flex items-center gap-3">
            {unread > 0 && (
              <button
                type="button"
                onClick={() => actions.markAllRead.mutate()}
                disabled={actions.markAllRead.isPending}
                className="font-body text-xs text-muted-foreground transition-colors duration-base hover:text-foreground disabled:opacity-50"
              >
                {actions.markAllRead.isPending ? t("notif.marking") : t("notif.markAllRead")}
              </button>
            )}
            {readCount > 0 && (
              <button
                type="button"
                onClick={() => setConfirmClear(true)}
                disabled={actions.clearRead.isPending}
                className="font-body text-xs text-muted-foreground transition-colors duration-base hover:text-foreground disabled:opacity-50"
              >
                {t("notif.clearRead")}
              </button>
            )}
          </span>
        </div>
        <ul className="max-h-96 overflow-y-auto font-body">
          {listQ.isLoading ? (
            <li className="px-3 py-8 text-center font-body text-sm text-muted-foreground">
              {t("common.loading")}
            </li>
          ) : listQ.isError ? (
            <li className="flex flex-col items-center gap-2 px-3 py-8 text-center font-body text-sm text-muted-foreground">
              {t("notif.errorBody")}
              <button
                type="button"
                onClick={() => listQ.refetch()}
                className="font-body text-xs text-primary transition-colors duration-base hover:text-primary/80"
              >
                {t("notif.retry")}
              </button>
            </li>
          ) : items.length ? (
            items.map((n) => (
              <NotificationRow
                key={n.id}
                n={n}
                actions={actions}
                onNavigate={(href) => {
                  setOpen(false);
                  router.push(href);
                }}
              />
            ))
          ) : (
            <li className="px-3 py-8 text-center font-body text-sm text-muted-foreground">
              {t("notif.empty")}
            </li>
          )}
        </ul>
        <p className="border-t border-border bg-muted/40 px-3 py-2 text-center">
          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="font-body text-xs text-muted-foreground transition-colors duration-base hover:text-foreground"
          >
            {atCap ? t("notif.viewAllCap", { n: NOTIF_CAP }) : t("notif.viewAll")}
          </Link>
        </p>
      </PopoverContent>

      <Dialog open={confirmClear} onOpenChange={setConfirmClear}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("notif.clearConfirm.title")}</DialogTitle>
            <DialogDescription>{t("notif.clearConfirm.body")}</DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirmClear(false)}>
              {t("notif.clearConfirm.cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                actions.clearRead.mutate(undefined, {
                  onSettled: () => setConfirmClear(false),
                });
              }}
              disabled={actions.clearRead.isPending}
            >
              {actions.clearRead.isPending
                ? t("notif.clearConfirm.clearing")
                : t("notif.clearConfirm.confirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Popover>
  );
}
