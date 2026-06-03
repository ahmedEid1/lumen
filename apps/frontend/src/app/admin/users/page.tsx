"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";
import type { Role } from "@/lib/api/types";

/**
 * Admin users — Workbench repaint.
 *
 * Dense table on the page background, header in mono uppercase, rows
 * separated by hairline borders, no nested card chrome. Email + last
 * login render in mono so admins can copy/scan IDs cleanly.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

type AdminUser = {
  id: string;
  email: string;
  full_name: string;
  // S1.11: the two-role model. Reads may still surface a legacy value during
  // the Phase-A window, but the role <Select> only ever assigns user/admin.
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
};

export default function AdminUsers() {
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const t = useT();
  const [q, setQ] = useState("");

  const usersQ = useQuery({
    queryKey: ["admin", "users", q],
    // Ask for the endpoint's max (le=200). The default is 50, and this flat
    // table has no pagination — without limit=200 an instance with 50-200
    // users would silently drop the rest with no indicator. Past 200 needs a
    // real cursor on the backend (deferred); 200 covers a portfolio-scale box.
    queryFn: () =>
      api<AdminUser[]>(
        `/api/v1/admin/users?limit=200${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
  });

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) =>
      api(`/api/v1/admin/users/${id}/role`, { method: "PATCH", body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (e: Error) => toast.error(e?.message ?? t("adminUsers.roleError")),
  });

  const setActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api(`/api/v1/admin/users/${id}/active`, { method: "PATCH", body: { is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (e: Error) => toast.error(e?.message ?? t("adminUsers.activeError")),
  });

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

      <DataTable<AdminUser>
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
              <Badge variant="muted">{t(`adminUsers.role.${u.role}` as MessageKey)}</Badge>
            ),
          },
          {
            id: "active",
            header: t("adminUsers.col.active"),
            cell: (u) =>
              u.is_active ? (
                <Badge>{t("adminUsers.status.active")}</Badge>
              ) : (
                <Badge variant="muted">{t("adminUsers.status.disabled")}</Badge>
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
            cell: (u) => (
              <div className="flex justify-end gap-2">
                <Select
                  value={u.role}
                  disabled={u.id === me?.id}
                  onValueChange={(v) => setRole.mutate({ id: u.id, role: v })}
                >
                  <SelectTrigger
                    aria-label={t("adminUsers.roleLabel")}
                    className="h-8 w-auto min-w-[8rem] text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {/* S1.11: only the two assignable roles. A row still
                        carrying a legacy value renders blank until reassigned;
                        the backend rejects writing legacy roles (422). */}
                    <SelectItem value="user">{t("adminUsers.role.user")}</SelectItem>
                    <SelectItem value="admin">{t("adminUsers.role.admin")}</SelectItem>
                  </SelectContent>
                </Select>
                {u.id !== me?.id && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setActive.mutate({ id: u.id, is_active: !u.is_active })
                    }
                  >
                    {u.is_active ? t("adminUsers.disable") : t("adminUsers.enable")}
                  </Button>
                )}
              </div>
            ),
          },
        ] as Column<AdminUser>[]}
        rows={usersQ.data ?? []}
        rowKey={(u) => u.id}
        loading={usersQ.isLoading}
        emptyState={
          <p className="font-body text-sm text-muted-foreground">
            {t("adminUsers.empty")}
          </p>
        }
      />
    </div>
  );
}
