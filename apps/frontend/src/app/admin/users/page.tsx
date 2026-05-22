"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

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
  role: "student" | "instructor" | "admin";
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
    queryFn: () =>
      api<AdminUser[]>(`/api/v1/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
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

  const selectClass =
    "h-8 rounded-md border border-border bg-muted px-2 font-body text-xs text-foreground transition-colors duration-[160ms] focus-visible:border-ring focus-visible:bg-background focus-visible:outline-none";

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

      <div className="surface overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/40 font-mono text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-4 py-3 text-start font-medium">{t("adminUsers.col.user")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminUsers.col.role")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminUsers.col.active")}</th>
                <th className="px-4 py-3 text-start font-medium">{t("adminUsers.col.lastLogin")}</th>
                <th className="px-4 py-3 text-end font-medium">{t("adminUsers.col.actions")}</th>
              </tr>
            </thead>
            <tbody className="font-body">
              {usersQ.data?.map((u) => (
                <tr
                  key={u.id}
                  className="border-t border-border transition-colors duration-[160ms] hover:bg-muted/30"
                >
                  <td className="px-4 py-3">
                    <div className="font-body text-sm font-medium text-foreground">
                      {u.full_name || "—"}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">{u.email}</div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="muted">{t(`adminUsers.role.${u.role}` as MessageKey)}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_active ? (
                      <Badge>{t("adminUsers.status.active")}</Badge>
                    ) : (
                      <Badge variant="muted">{t("adminUsers.status.disabled")}</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <select
                        className={selectClass}
                        value={u.role}
                        disabled={u.id === me?.id}
                        onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}
                      >
                        <option value="student">{t("adminUsers.role.student")}</option>
                        <option value="instructor">{t("adminUsers.role.instructor")}</option>
                        <option value="admin">{t("adminUsers.role.admin")}</option>
                      </select>
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
                  </td>
                </tr>
              ))}
              {!usersQ.data?.length && (
                <tr>
                  <td colSpan={5} className="px-4 py-12">
                    <p className="text-center font-body text-sm text-muted-foreground">
                      {t("adminUsers.empty")}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
