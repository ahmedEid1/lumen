"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Admin } from "@/lib/api/endpoints";
import { ALL_REASON_CODES, type ReasonCode, type UserAdminOut } from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";
import { useReturnFocus } from "@/lib/a11y/use-return-focus";

/**
 * Admin users (S6.11 / FR-ADMIN-01/03/08).
 *
 * S1 collapsed the role model to `{user, admin}`. S6 replaces the role
 * `<Select>` write path with a grant/revoke-admin toggle plus first-class
 * suspend/reinstate. The current admin's OWN row has its grant/revoke +
 * suspend controls disabled (FR-ADMIN-01); the last-admin invariant is
 * enforced authoritatively on the backend (422) and surfaced inline here
 * (FR-ADMIN-08). Grant/revoke/suspend each go through a confirmation dialog.
 */

// The pending mutation a confirmation dialog will run on confirm.
type PendingAction =
  | { kind: "grant"; user: UserAdminOut }
  | { kind: "revoke"; user: UserAdminOut }
  | { kind: "suspend"; user: UserAdminOut };

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const t = useT();
  const [q, setQ] = useState("");
  const [pending, setPending] = useState<PendingAction | null>(null);

  const usersQ = useQuery({
    queryKey: [...qk.adminUsers, q] as const,
    queryFn: () => Admin.users({ q: q || undefined }),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: qk.adminUsers });

  // Reinstate is non-destructive — no confirmation dialog.
  const reinstate = useMutation({
    mutationFn: (id: string) => Admin.reinstateUser(id),
    onSuccess: () => {
      toast.success(t("adminUsers.reinstateToast"));
      invalidate();
    },
    onError: (e: Error) => toast.error(e?.message ?? t("adminUsers.toggleError")),
  });

  const rows = usersQ.data ?? [];

  return (
    <div className="container mx-auto max-w-6xl px-6 py-14">
      <header className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-3">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("adminUsers.cartouche")}
          </p>
          <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
            {t("adminUsers.title")}
          </h1>
          <p className="font-body text-sm text-muted-foreground">{t("adminUsers.subtitle")}</p>
        </div>
        <div className="relative sm:w-72">
          <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("adminUsers.searchPlaceholder")}
            className="ps-9"
          />
        </div>
      </header>

      <DataTable<UserAdminOut>
        ariaLabel={t("adminUsers.title")}
        columns={[
          {
            id: "user",
            header: t("adminUsers.col.user"),
            cell: (u) => (
              <div>
                <div className="font-body text-sm font-medium text-foreground">
                  {u.full_name || "—"}
                </div>
                <div className="font-mono text-xs text-muted-foreground">{u.email}</div>
              </div>
            ),
          },
          {
            id: "role",
            header: t("adminUsers.col.role"),
            cell: (u) => (
              <Badge variant={u.role === "admin" ? "default" : "muted"}>
                {t(`adminUsers.role.${u.role}` as MessageKey)}
              </Badge>
            ),
          },
          {
            id: "status",
            header: t("adminUsers.col.status"),
            cell: (u) =>
              u.is_active ? (
                <Badge>{t("adminUsers.status.active")}</Badge>
              ) : (
                <Badge variant="muted">{t("adminUsers.status.suspended")}</Badge>
              ),
          },
          {
            id: "lastLogin",
            header: t("adminUsers.col.lastLogin"),
            cell: (u) => (
              <span className="font-mono text-xs text-muted-foreground">
                {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
              </span>
            ),
          },
          {
            id: "actions",
            header: t("adminUsers.col.actions"),
            headerClassName: "text-end",
            className: "text-end",
            cell: (u) => {
              const isSelf = u.id === me?.id;
              return (
                <div className="flex justify-end gap-2">
                  {/* Grant/revoke admin toggle (FR-ADMIN-01). Self-row disabled. */}
                  {u.role === "admin" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isSelf}
                      title={isSelf ? t("adminUsers.selfRowHint") : undefined}
                      onClick={() => setPending({ kind: "revoke", user: u })}
                    >
                      {t("adminUsers.revokeAdmin")}
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isSelf}
                      title={isSelf ? t("adminUsers.selfRowHint") : undefined}
                      onClick={() => setPending({ kind: "grant", user: u })}
                    >
                      {t("adminUsers.grantAdmin")}
                    </Button>
                  )}
                  {/* Suspend / reinstate (FR-SUSP-01/02). Self-row suspend disabled. */}
                  {u.is_active ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isSelf}
                      title={isSelf ? t("adminUsers.selfRowHint") : undefined}
                      onClick={() => setPending({ kind: "suspend", user: u })}
                    >
                      {t("adminUsers.suspend")}
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={reinstate.isPending}
                      onClick={() => reinstate.mutate(u.id)}
                    >
                      {t("adminUsers.reinstate")}
                    </Button>
                  )}
                </div>
              );
            },
          },
        ] as Column<UserAdminOut>[]}
        rows={rows}
        rowKey={(u) => u.id}
        loading={usersQ.isLoading}
        emptyState={
          <p className="font-body text-sm text-muted-foreground">{t("adminUsers.empty")}</p>
        }
      />

      <UserActionDialog
        action={pending}
        onClose={() => setPending(null)}
        onDone={invalidate}
      />
    </div>
  );
}

// ---------------- Confirmation dialog for grant / revoke / suspend ----------------

function UserActionDialog({
  action,
  onClose,
  onDone,
}: {
  action: PendingAction | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const open = action !== null;
  const onCloseAutoFocus = useReturnFocus(open);

  useEffect(() => {
    if (open) {
      setReason("");
      setNote("");
    }
  }, [open, action?.user.id]);

  const run = useMutation({
    mutationFn: () => {
      if (!action) throw new Error("no action");
      switch (action.kind) {
        case "grant":
          return Admin.setAdmin(action.user.id, true);
        case "revoke":
          return Admin.setAdmin(action.user.id, false);
        case "suspend":
          return Admin.suspendUser(action.user.id, {
            reason: (reason || "other") as ReasonCode,
            note: note || null,
          });
      }
    },
    onSuccess: () => {
      const toastKey: MessageKey =
        action?.kind === "grant"
          ? "adminUsers.grantToast"
          : action?.kind === "revoke"
            ? "adminUsers.revokeToast"
            : "adminUsers.suspendToast";
      toast.success(t(toastKey));
      onDone();
      onClose();
    },
    onError: (e: Error) => {
      // Surface the backend invariant codes inline (FR-ADMIN-08). The error
      // message is the server's; toast it so the admin sees e.g. last-admin.
      toast.error(e?.message ?? t("adminUsers.toggleError"));
      onClose();
    },
  });

  if (!action) return null;

  const titleKey: MessageKey =
    action.kind === "grant"
      ? "adminUsers.confirmGrantTitle"
      : action.kind === "revoke"
        ? "adminUsers.confirmRevokeTitle"
        : "adminUsers.confirmSuspendTitle";
  const bodyKey: MessageKey =
    action.kind === "grant"
      ? "adminUsers.confirmGrantBody"
      : action.kind === "revoke"
        ? "adminUsers.confirmRevokeBody"
        : "adminUsers.confirmSuspendBody";

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle className={action.kind === "suspend" ? "text-destructive" : undefined}>
            {t(titleKey)}
          </DialogTitle>
          <DialogDescription>{t(bodyKey)}</DialogDescription>
        </DialogHeader>

        {action.kind === "suspend" ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="font-body text-sm font-medium">
                {t("adminModeration.reasonLabel")}
              </label>
              <Select value={reason} onValueChange={(v) => setReason(v as ReasonCode)}>
                <SelectTrigger aria-label={t("adminModeration.reasonLabel")}>
                  <SelectValue placeholder={t("adminModeration.reasonPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {ALL_REASON_CODES.map((code) => (
                    <SelectItem key={code} value={code}>
                      {t(`reason.${code}` as MessageKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="suspend-note" className="font-body text-sm font-medium">
                {t("adminModeration.noteLabel")}
              </label>
              <Textarea
                id="suspend-note"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("adminModeration.notePlaceholder")}
              />
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant={action.kind === "suspend" ? "destructive" : "default"}
            data-testid="confirm-user-action"
            disabled={run.isPending}
            onClick={() => run.mutate()}
          >
            {t("adminUsers.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
