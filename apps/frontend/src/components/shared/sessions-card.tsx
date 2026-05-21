"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { LogOut, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";
import { formatRelative } from "@/lib/utils";

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
  const q = useQuery({
    queryKey: KEY,
    queryFn: () => api<Session[]>("/api/v1/users/me/sessions"),
  });

  const revokeOne = useMutation({
    mutationFn: (id: string) => api(`/api/v1/users/me/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Session revoked");
      qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not revoke session"),
  });

  const revokeAll = useMutation({
    mutationFn: () => api("/api/v1/users/me/sessions", { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Signed out of all sessions — sign in again to continue");
      qc.invalidateQueries({ queryKey: KEY });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not revoke sessions"),
  });

  const sessions = q.data ?? [];
  const active = sessions.filter((s) => !s.revoked_at);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Active sessions</CardTitle>
            <CardDescription>
              {active.length} active · last 50 sign-ins listed below
            </CardDescription>
          </div>
          {active.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => revokeAll.mutate()}
              disabled={revokeAll.isPending}
            >
              <LogOut className="me-1 h-4 w-4" /> Sign out everywhere
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : sessions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sessions on record.</p>
        ) : (
          <ul className="divide-y">
            {sessions.map((s) => (
              <li key={s.id} className="flex items-start justify-between gap-3 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium">
                    {s.user_agent ?? "Unknown device"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {s.ip_address ?? "—"} · signed in {formatRelative(s.issued_at)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {s.revoked_at ? (
                      <span>revoked {formatRelative(s.revoked_at)}</span>
                    ) : (
                      <span>expires {formatRelative(s.expires_at)}</span>
                    )}
                  </p>
                </div>
                {!s.revoked_at && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="Revoke session"
                    onClick={() => revokeOne.mutate(s.id)}
                    disabled={revokeOne.isPending}
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
