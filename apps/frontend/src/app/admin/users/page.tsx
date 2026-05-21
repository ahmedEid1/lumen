"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

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

  return (
    <div className="container mx-auto max-w-5xl px-4 py-14">
      <header className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-3">
          <Cartouche>{t("adminUsers.cartouche")}</Cartouche>
          <h1 className="font-display text-3xl font-medium tracking-tight">
            {t("adminUsers.title")}
          </h1>
          <p className="font-body text-muted-foreground">{t("adminUsers.subtitle")}</p>
        </div>
        <div className="relative sm:w-72">
          <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gold/60" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("adminUsers.searchPlaceholder")}
            className="border-gold/25 bg-background/60 ps-9 focus-visible:border-gold/60"
          />
        </div>
      </header>

      <Card className="scroll-paper border-gold/20">
        <CardHeader>
          <CardTitle className="font-display text-xl">{t("adminUsers.recentCard")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gold/15 bg-muted/30 text-[0.65rem] uppercase tracking-[0.28em] text-gold/70">
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
                    className="border-t border-border transition-colors hover:bg-muted/20"
                  >
                    <td className="px-4 py-3">
                      <div className="font-display text-base font-medium">{u.full_name || "—"}</div>
                      <div className="text-xs text-muted-foreground">{u.email}</div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="muted">
                        {t(`adminUsers.role.${u.role}` as MessageKey)}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {u.is_active ? (
                        <Badge className="border border-gold/40 bg-gold/10 text-gold">
                          {t("adminUsers.status.active")}
                        </Badge>
                      ) : (
                        <Badge variant="muted">{t("adminUsers.status.disabled")}</Badge>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <select
                          className="h-8 rounded-md border border-gold/25 bg-background/60 px-2 font-body text-xs focus-visible:border-gold/60"
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
                      <div className="flex flex-col items-center gap-3 text-center">
                        <Glyph
                          name="ankh"
                          size={40}
                          mode="tint"
                          className="text-gold/40"
                        />
                        <p className="font-body italic text-muted-foreground">
                          {t("adminUsers.empty")}
                        </p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
