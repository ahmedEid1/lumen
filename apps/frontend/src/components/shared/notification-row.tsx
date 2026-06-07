"use client";

/**
 * Shared notification row + cache-aware action hook.
 *
 * Used by both the bell popover and the /notifications inbox page so the
 * two surfaces render and behave identically (same deep links, same kebab
 * actions, same optimistic cache updates).
 *
 * A11y shape (axe: no nested-interactive): the <li> contains a real
 * <button> navigation control and a SIBLING kebab DropdownMenu trigger —
 * never actions nested inside a clickable container. Non-navigable kinds
 * (security.*, account.*) render the same content as a plain <div>: not
 * presented as clickable, but still read/delete-able via the kebab.
 */

import { useMemo } from "react";
import { useMutation, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import {
  AtSign,
  Award,
  Bell,
  BookOpen,
  Copy,
  GraduationCap,
  MessageSquare,
  MoreHorizontal,
  ShieldAlert,
  Star,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Me } from "@/lib/api/endpoints";
import {
  targetHref,
  type NotificationInboxPage,
  type NotificationItem,
} from "@/lib/notifications";
import { qk } from "@/lib/query/keys";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

// ---------------------------------------------------------------- kind icons

/** kind → icon + tone. Security/account alarms get a distinct warning tone
 * (shape AND color differ — color is never the only differentiator).
 * Unknown future sub-kinds fall back to the bell. */
function kindVisual(kind: string): { Icon: LucideIcon; tone: "default" | "warning" } {
  if (kind.startsWith("security") || kind.startsWith("account")) {
    return { Icon: ShieldAlert, tone: "warning" };
  }
  switch (kind) {
    case "enrolled":
      return { Icon: GraduationCap, tone: "default" };
    case "lesson_available":
      return { Icon: BookOpen, tone: "default" };
    case "certificate_ready":
      return { Icon: Award, tone: "default" };
    case "review_received":
      return { Icon: Star, tone: "default" };
    case "discussion_reply":
      return { Icon: MessageSquare, tone: "default" };
    case "chat_mention":
      return { Icon: AtSign, tone: "default" };
    case "course_cloned":
      return { Icon: Copy, tone: "default" };
    default:
      return { Icon: Bell, tone: "default" };
  }
}

// ------------------------------------------------------- optimistic plumbing

type CountData = { unread_count: number } | undefined;
type ListData = NotificationItem[] | undefined;
type InboxData = InfiniteData<NotificationInboxPage> | undefined;

/** Apply `fn` (return null to remove the row) across every notification
 * cache for this viewer: the bell's bare list, and both inbox filters.
 * The unread-filtered inbox additionally drops rows that no longer match. */
function patchRowCaches(
  qc: ReturnType<typeof useQueryClient>,
  viewerId: string,
  fn: (n: NotificationItem) => NotificationItem | null,
) {
  qc.setQueryData<ListData>([...qk.notifications, viewerId], (old) =>
    old ? (old.map(fn).filter(Boolean) as NotificationItem[]) : old,
  );
  for (const filter of ["all", "unread"] as const) {
    qc.setQueryData<InboxData>([...qk.notificationsInbox, viewerId, filter], (old) => {
      if (!old) return old;
      return {
        ...old,
        pages: old.pages.map((p) => ({
          ...p,
          items: p.items
            .map(fn)
            .filter((n): n is NotificationItem => n !== null)
            .filter((n) => (filter === "unread" ? n.read_at === null : true)),
        })),
      };
    });
  }
}

function adjustCount(
  qc: ReturnType<typeof useQueryClient>,
  viewerId: string,
  delta: number,
) {
  qc.setQueryData<CountData>([...qk.notificationsCount, viewerId], (old) =>
    old ? { unread_count: Math.max(0, old.unread_count + delta) } : old,
  );
}

/** Find a row in any of this viewer's caches (for "was it unread?"). */
function findRow(
  qc: ReturnType<typeof useQueryClient>,
  viewerId: string,
  id: string,
): NotificationItem | undefined {
  const list = qc.getQueryData<ListData>([...qk.notifications, viewerId]);
  const inList = list?.find((n) => n.id === id);
  if (inList) return inList;
  for (const filter of ["all", "unread"] as const) {
    const inbox = qc.getQueryData<InboxData>([...qk.notificationsInbox, viewerId, filter]);
    const hit = inbox?.pages.flatMap((p) => p.items).find((n) => n.id === id);
    if (hit) return hit;
  }
  return undefined;
}

/**
 * Cache-aware notification mutations, shared by bell + inbox page.
 *
 * Every mutation: optimistic patch across all three caches → rollback on
 * error (with toast) → prefix-invalidate on settle so the server state
 * reconciles. `viewerId` scopes the caches per identity (the Codex-caught
 * cross-account-leak rule from the tutor panel applies here too).
 */
export function useNotificationActions(viewerId: string | null) {
  const qc = useQueryClient();
  const t = useT();
  const vid = viewerId ?? "anon";

  const snapshotAndPatch = async (
    fn: (n: NotificationItem) => NotificationItem | null,
    delta: (row: NotificationItem | undefined) => number,
    id?: string,
  ) => {
    await qc.cancelQueries({ queryKey: qk.notifications });
    const snapshot = qc.getQueriesData({ queryKey: qk.notifications });
    const row = id ? findRow(qc, vid, id) : undefined;
    patchRowCaches(qc, vid, fn);
    adjustCount(qc, vid, delta(row));
    return { snapshot };
  };

  const rollback = (ctx: unknown) => {
    const snapshot = (ctx as { snapshot?: [readonly unknown[], unknown][] })?.snapshot;
    if (snapshot) {
      for (const [key, data] of snapshot) {
        qc.setQueryData(key as readonly unknown[], data);
      }
    }
    toast.error(t("notif.actionError"));
  };

  const settle = () => qc.invalidateQueries({ queryKey: qk.notifications });

  const markRead = useMutation({
    mutationFn: (id: string) => Me.markNotificationRead(id),
    onMutate: (id) =>
      snapshotAndPatch(
        (n) => (n.id === id && !n.read_at ? { ...n, read_at: new Date().toISOString() } : n),
        (row) => (row && !row.read_at ? -1 : 0),
        id,
      ),
    onError: (_e, _id, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const markUnread = useMutation({
    mutationFn: (id: string) => Me.markNotificationUnread(id),
    onMutate: (id) =>
      snapshotAndPatch(
        (n) => (n.id === id && n.read_at ? { ...n, read_at: null } : n),
        (row) => (row?.read_at ? 1 : 0),
        id,
      ),
    onError: (_e, _id, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const remove = useMutation({
    mutationFn: (id: string) => Me.deleteNotification(id),
    onMutate: (id) =>
      snapshotAndPatch(
        (n) => (n.id === id ? null : n),
        (row) => (row && !row.read_at ? -1 : 0),
        id,
      ),
    onSuccess: () => toast.success(t("notif.deleted")),
    onError: (_e, _id, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const markAllRead = useMutation({
    mutationFn: () => Me.markAllNotificationsRead(),
    onMutate: () =>
      snapshotAndPatch(
        (n) => (n.read_at ? n : { ...n, read_at: new Date().toISOString() }),
        () => 0,
      ).then(async (ctx) => {
        qc.setQueryData<CountData>([...qk.notificationsCount, vid], (old) =>
          old ? { unread_count: 0 } : old,
        );
        return ctx;
      }),
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settle,
  });

  const clearRead = useMutation({
    mutationFn: () => Me.clearNotifications("read"),
    onMutate: () =>
      snapshotAndPatch(
        (n) => (n.read_at ? null : n),
        () => 0,
      ),
    onSuccess: (res) => toast.success(t("notif.cleared", { n: res.deleted })),
    onError: (_e, _v, ctx) => rollback(ctx),
    onSettled: settle,
  });

  return { markRead, markUnread, remove, markAllRead, clearRead };
}

// ------------------------------------------------------------------- the row

export function NotificationRow({
  n,
  actions,
  onNavigate,
}: {
  n: NotificationItem;
  actions: ReturnType<typeof useNotificationActions>;
  onNavigate?: (href: string) => void;
}) {
  const t = useT();
  const href = useMemo(() => targetHref(n), [n]);
  const { Icon, tone } = kindVisual(n.kind);
  const unread = !n.read_at;

  const body = (
    <>
      <span className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          {unread && (
            <>
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
              <span className="sr-only">{t("notif.unreadSr")}</span>
            </>
          )}
          <strong className="truncate font-medium text-foreground">{n.title}</strong>
        </span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground">
          {formatRelative(n.created_at)}
        </span>
      </span>
      {n.body && (
        <span className="block truncate text-xs text-muted-foreground">{n.body}</span>
      )}
    </>
  );

  return (
    <li
      className={`flex items-start gap-1 border-b border-border ps-3 pe-1 py-2 text-sm last:border-0 transition-colors duration-base ${
        unread ? "bg-muted/30" : ""
      }`}
    >
      <Icon
        aria-hidden
        className={`mt-1.5 h-4 w-4 shrink-0 ${
          tone === "warning" ? "text-amber-500" : "text-muted-foreground"
        }`}
      />
      {href ? (
        <button
          type="button"
          onClick={() => {
            if (unread) actions.markRead.mutate(n.id);
            onNavigate?.(href);
          }}
          className="min-w-0 flex-1 rounded-sm px-1 py-0.5 text-start outline-none transition-colors duration-base hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
        >
          {body}
        </button>
      ) : (
        <div className="min-w-0 flex-1 px-1 py-0.5">{body}</div>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={t("notif.rowActions", { title: n.title })}
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {unread ? (
            <DropdownMenuItem onSelect={() => actions.markRead.mutate(n.id)}>
              {t("notif.markRead")}
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onSelect={() => actions.markUnread.mutate(n.id)}>
              {t("notif.markUnread")}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            className="text-destructive focus:text-destructive"
            onSelect={() => actions.remove.mutate(n.id)}
          >
            {t("notif.delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}
