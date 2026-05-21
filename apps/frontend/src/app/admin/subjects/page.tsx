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

export default function AdminSubjects() {
  const qc = useQueryClient();
  const subjectsQ = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () => api("/api/v1/admin/subjects", { method: "POST", body: { title, slug: slug || undefined } }),
    onSuccess: () => {
      toast.success("Subject added");
      setTitle("");
      setSlug("");
      qc.invalidateQueries({ queryKey: qk.subjects });
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not add"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/admin/subjects/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.subjects }),
    onError: (e: any) => toast.error(e?.message ?? "Could not delete"),
  });

  return (
    <div className="container mx-auto max-w-3xl px-4 py-10">
      <h1 className="mb-4 text-2xl font-bold tracking-tight">Subjects</h1>
      <Card>
        <CardHeader>
          <CardTitle>Add subject</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <Input
              placeholder="Title (e.g. Programming)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
            <Input placeholder="Slug (optional)" value={slug} onChange={(e) => setSlug(e.target.value)} />
            <Button type="submit" disabled={!title || create.isPending}>
              <Plus className="mr-1 h-4 w-4" /> Add
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>All subjects</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="divide-y">
            {subjectsQ.data?.map((s) => (
              <li key={s.id} className="flex items-center justify-between py-2">
                <div>
                  <div className="font-medium">{s.title}</div>
                  <div className="text-xs text-muted-foreground">/{s.slug}</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">
                    {s.total_courses ?? 0} courses
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => remove.mutate(s.id)}
                    aria-label="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
            {!subjectsQ.data?.length && (
              <li className="py-6 text-center text-sm text-muted-foreground">No subjects yet.</li>
            )}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
