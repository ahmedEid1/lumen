"use client";

/**
 * Notifications inbox — the full, cursor-paged history surface.
 *
 * The bell popover shows only the newest 50; this page walks the entire
 * history via `GET /me/notifications/inbox` (keyset cursor, no cap) with a
 * server-side All/Unread filter. Rows render through the shared
 * `NotificationRow` so deep links, kebab actions (read/unread toggle,
 * delete), and optimistic cache behaviour are identical to the bell.
 *
 * Workbench rules: mono cartouche + display h1, `surface` list container,
 * borders not shadows, counts in mono. Auth-gated like dashboard/reviews.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/client";
import { Me } from "@/lib/api/endpoints";
import {
  NotificationRow,
  useNotificationActions,
} from "@/components/shared/notification-row";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

type Filter = "all" | "unread";

export default function NotificationsPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();
  const [filter, setFilter] = useState<Filter>("all");
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/notifications");
  }, [ready, user, router]);

  const userId = user?.id ?? null;
  const actions = useNotificationActions(userId);

  const countQ = useQuery({
    queryKey: [...qk.notificationsCount, userId],
    queryFn: () => Me.notificationUnreadCount(),
    enabled: !!userId,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 401 ? false : failureCount < 2,
  });

  const inboxQ = useInfiniteQuery({
    queryKey: [...qk.notificationsInbox, userId, filter],
    queryFn: ({ pageParam }) =>
      Me.notificationsInbox({
        cursor: pageParam,
        limit: 20,
        unread: filter === "unread",
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: !!userId,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 401 ? false : failureCount < 2,
  });

  if (!ready || !user) return null;

  const items = inboxQ.data?.pages.flatMap((p) => p.items) ?? [];
  const unread = countQ.data?.unread_count ?? 0;
  const readVisible = items.filter((n) => n.read_at).length;

  return (
    <div className="container mx-auto max-w-3xl px-6 py-14 sm:py-20">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("notif.page.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("notif.page.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("notif.page.subtitle")}
        </p>
      </header>

      {/* Tabs root wraps BOTH the trigger row and real TabsContent panels —
          a TabsTrigger without a mounted panel emits a dangling
          aria-controls, which the axe gate flags as a critical
          aria-valid-attr-value violation. Radix keeps the inactive panel
          mounted-but-hidden, so both references resolve; only the active
          panel renders the (filter-driven) list body. */}
      <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)}>
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <TabsList>
            <TabsTrigger value="all">{t("notif.page.tabs.all")}</TabsTrigger>
            <TabsTrigger value="unread">
              {t("notif.page.tabs.unread")}
              {unread > 0 && (
                <span className="ms-1.5 font-mono text-xs tabular-nums">{unread}</span>
              )}
            </TabsTrigger>
          </TabsList>
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
            {readVisible > 0 && (
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

        {(["all", "unread"] as const).map((tab) => (
          <TabsContent key={tab} value={tab} className="mt-0">
            {filter !== tab ? null : inboxQ.isLoading ? (
              <div className="surface h-32 animate-pulse" aria-hidden />
            ) : inboxQ.isError ? (
              <div className="surface flex flex-col items-center gap-2 px-5 py-10 text-center">
                <p className="font-body text-sm text-muted-foreground">
                  {t("notif.errorBody")}
                </p>
                <button
                  type="button"
                  onClick={() => inboxQ.refetch()}
                  className="font-body text-sm text-primary transition-colors duration-base hover:text-primary/80"
                >
                  {t("notif.retry")}
                </button>
              </div>
            ) : items.length === 0 ? (
              <div className="surface px-5 py-10 text-center">
                <p className="font-display text-base leading-tight tracking-tight">
                  {filter === "unread" ? t("notif.allCaughtUp") : t("notif.empty")}
                </p>
                {filter === "unread" && (
                  <p className="mt-2 font-body text-sm text-muted-foreground">
                    {t("notif.allCaughtUpBody")}
                  </p>
                )}
              </div>
            ) : (
              <>
                <ul className="surface overflow-hidden p-0 font-body">
                  {items.map((n) => (
                    <NotificationRow
                      key={n.id}
                      n={n}
                      actions={actions}
                      onNavigate={(href) => router.push(href)}
                    />
                  ))}
                </ul>
                {inboxQ.hasNextPage && (
                  <div className="mt-5 flex justify-center">
                    <Button
                      variant="outline"
                      onClick={() => inboxQ.fetchNextPage()}
                      disabled={inboxQ.isFetchingNextPage}
                    >
                      {inboxQ.isFetchingNextPage
                        ? t("common.loading")
                        : t("notif.page.loadMore")}
                    </Button>
                  </div>
                )}
              </>
            )}
          </TabsContent>
        ))}
      </Tabs>

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
    </div>
  );
}
