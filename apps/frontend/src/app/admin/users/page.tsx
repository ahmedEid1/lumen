"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";

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
  const [q, setQ] = useState("");

  const usersQ = useQuery({
    queryKey: ["admin", "users", q],
    queryFn: () => api<AdminUser[]>(`/api/v1/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  });

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) =>
      api(`/api/v1/admin/users/${id}/role`, { method: "PATCH", body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (e: Error) => toast.error(e?.message ?? "Could not update role"),
  });

  const setActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      api(`/api/v1/admin/users/${id}/active`, { method: "PATCH", body: { is_active } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
    onError: (e: Error) => toast.error(e?.message ?? "Could not update"),
  });

  return (
    <div className="container mx-auto max-w-5xl px-4 py-10">
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Users</h1>
          <p className="text-muted-foreground">Promote instructors, deactivate accounts.</p>
        </div>
        <div className="relative w-72">
          <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search email or name…"
            className="ps-9"
          />
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Recent</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-start">
                <tr>
                  <th className="px-4 py-2">User</th>
                  <th className="px-4 py-2">Role</th>
                  <th className="px-4 py-2">Active</th>
                  <th className="px-4 py-2">Last login</th>
                  <th className="px-4 py-2 text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                {usersQ.data?.map((u) => (
                  <tr key={u.id} className="border-t">
                    <td className="px-4 py-2">
                      <div className="font-medium">{u.full_name || "—"}</div>
                      <div className="text-xs text-muted-foreground">{u.email}</div>
                    </td>
                    <td className="px-4 py-2 capitalize">
                      <Badge variant="muted">{u.role}</Badge>
                    </td>
                    <td className="px-4 py-2">
                      {u.is_active ? (
                        <Badge variant="default">active</Badge>
                      ) : (
                        <Badge variant="muted">disabled</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex justify-end gap-2">
                        <select
                          className="h-8 rounded-md border bg-background px-2 text-xs"
                          value={u.role}
                          disabled={u.id === me?.id}
                          onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}
                        >
                          <option value="student">student</option>
                          <option value="instructor">instructor</option>
                          <option value="admin">admin</option>
                        </select>
                        {u.id !== me?.id && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setActive.mutate({ id: u.id, is_active: !u.is_active })
                            }
                          >
                            {u.is_active ? "Disable" : "Enable"}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {!usersQ.data?.length && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                      No users.
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
