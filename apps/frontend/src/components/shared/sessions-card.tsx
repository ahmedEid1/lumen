"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { LogOut, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { formatRelative } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";

type Session = {
  id: string;
  issued_at: string;
  expires_at: string;
  revoked_at: string | null;
  user_agent: string | null;
  ip_address: string | null;
};

const KEY = ["me", "sessions"] as const;

export function SessionsCard() {
  const qc = useQueryClient();
  const t = useT();
  const q = useQuery({
    queryKey: KEY,
    queryFn: () => api<Session[]>("/api/v1/users/me/sessions"),
  });

  const revokeOne = useMutation({
    mutationFn: (id: string) => api(`/api/v1/users/me/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("sessions.revokedToast"));
      qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("sessions.revokeError")),
  });

  const revokeAll = useMutation({
    mutationFn: () => api("/api/v1/users/me/sessions", { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("sessions.allRevokedToast"));
      qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("sessions.revokeAllError")),
  });

  const sessions = q.data ?? [];
  const active = sessions.filter((s) => !s.revoked_at);

  return (
    <Card className="surface">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="font-display text-lg leading-tight tracking-tight">
              {t("sessions.title")}
            </CardTitle>
            <CardDescription className="font-body text-sm">
              {t("sessions.description", { n: active.length })}
            </CardDescription>
          </div>
          {active.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => revokeAll.mutate()}
              disabled={revokeAll.isPending}
            >
              <LogOut className="me-1 h-4 w-4" /> {t("sessions.signOutAll")}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p className="font-body text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : sessions.length === 0 ? (
          <p className="font-body text-sm text-muted-foreground">{t("sessions.empty")}</p>
        ) : (
          <ul className="divide-y divide-border font-body">
            {sessions.map((s) => (
              <li key={s.id} className="flex items-start justify-between gap-3 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">
                    {s.user_agent ?? t("sessions.unknownDevice")}
                  </p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {s.ip_address ?? "—"} ·{" "}
                    {t("sessions.signedIn", { when: formatRelative(s.issued_at) })}
                  </p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {s.revoked_at
                      ? t("sessions.revoked", { when: formatRelative(s.revoked_at) })
                      : t("sessions.expires", { when: formatRelative(s.expires_at) })}
                  </p>
                </div>
                {!s.revoked_at && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("sessions.revoke")}
                    onClick={() => revokeOne.mutate(s.id)}
                    disabled={revokeOne.isPending}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
