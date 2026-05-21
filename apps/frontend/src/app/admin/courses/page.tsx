"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Search, Star, StarOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import type { CourseListItem } from "@/lib/api/types";

export default function AdminCourses() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [onlyFeatured, setOnlyFeatured] = useState(false);

  const KEY = ["admin", "courses", { q, onlyFeatured }] as const;
  const coursesQ = useQuery({
    queryKey: KEY,
    queryFn: () => {
      const qs = new URLSearchParams();
      if (q) qs.set("q", q);
      if (onlyFeatured) qs.set("only_featured", "true");
      return api<CourseListItem[]>(`/api/v1/admin/courses${qs.toString() ? `?${qs}` : ""}`);
    },
  });

  const toggle = useMutation({
    mutationFn: ({ id, next }: { id: string; next: boolean }) =>
      api<CourseListItem>(`/api/v1/admin/courses/${id}/feature`, {
        method: "PATCH",
        body: { is_featured: next },
      }),
    onSuccess: () => {
      toast.success("Updated");
      qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    },
    onError: (e: any) => toast.error(e?.message ?? "Could not update"),
  });

  return (
    <div className="container mx-auto max-w-5xl px-4 py-10">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Courses</h1>
          <p className="text-muted-foreground">Manage featured selection and oversee the catalog.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative w-72">
            <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search title or overview…"
              className="ps-9"
            />
          </div>
          <label className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={onlyFeatured}
              onChange={(e) => setOnlyFeatured(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            Featured only
          </label>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>All courses</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-start">
              <tr>
                <th className="px-4 py-2">Course</th>
                <th className="px-4 py-2">Owner</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Featured</th>
                <th className="px-4 py-2 text-end">Action</th>
              </tr>
            </thead>
            <tbody>
              {coursesQ.data?.map((c) => (
                <tr key={c.id} className="border-t align-middle">
                  <td className="px-4 py-2">
                    <Link
                      href={`/courses/${c.slug}`}
                      className="font-medium hover:underline"
                      target="_blank"
                    >
                      {c.title}
                    </Link>
                    <div className="text-xs text-muted-foreground">{c.subject.title}</div>
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{c.owner.full_name}</td>
                  <td className="px-4 py-2">
                    <Badge variant={c.status === "published" ? "default" : "muted"}>{c.status}</Badge>
                  </td>
                  <td className="px-4 py-2">
                    {c.is_featured ? (
                      <Badge>featured</Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-end">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggle.mutate({ id: c.id, next: !c.is_featured })}
                      disabled={toggle.isPending}
                    >
                      {c.is_featured ? (
                        <>
                          <StarOff className="me-1 h-4 w-4" /> Unfeature
                        </>
                      ) : (
                        <>
                          <Star className="me-1 h-4 w-4" /> Feature
                        </>
                      )}
                    </Button>
                  </td>
                </tr>
              ))}
              {!coursesQ.data?.length && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                    No courses match.
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
