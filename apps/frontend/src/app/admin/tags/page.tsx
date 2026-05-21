"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import { Catalog } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";

export default function AdminTags() {
  const qc = useQueryClient();
  const tagsQ = useQuery({ queryKey: qk.tags, queryFn: () => Catalog.tags() });
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: () => api("/api/v1/admin/tags", { method: "POST", body: { name } }),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: qk.tags });
    },
    onError: (e: Error) => toast.error(e?.message ?? "Could not add"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/admin/tags/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.tags }),
  });

  return (
    <div className="container mx-auto max-w-3xl px-4 py-10">
      <h1 className="mb-4 text-2xl font-bold tracking-tight">Tags</h1>
      <Card>
        <CardHeader>
          <CardTitle>Add tag</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Input
              placeholder="Name (e.g. Python)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <Button type="submit" disabled={!name || create.isPending}>
              <Plus className="me-1 h-4 w-4" /> Add
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>All tags</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-wrap gap-2">
            {tagsQ.data?.map((t) => (
              <li key={t.id} className="flex items-center gap-1 rounded-full border px-3 py-1 text-sm">
                {t.name}
                <button
                  onClick={() => remove.mutate(t.id)}
                  aria-label="Remove"
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
            {!tagsQ.data?.length && (
              <li className="w-full py-4 text-center text-sm text-muted-foreground">No tags yet.</li>
            )}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
