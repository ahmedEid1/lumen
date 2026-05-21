"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Courses } from "@/lib/api/endpoints";
import type { CourseListItem, CourseStatus } from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";

type FilterValue = "all" | CourseStatus;

const FILTERS: { value: FilterValue; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "published", label: "Published" },
  { value: "archived", label: "Archived" },
];

export default function StudioPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const mine = useQuery({ queryKey: qk.myCourses, queryFn: () => Courses.mine(), enabled: !!user });
  const [filter, setFilter] = useState<FilterValue>("all");

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace("/login?next=/studio");
    else if (user.role === "student") router.replace("/dashboard");
  }, [ready, user, router]);

  const counts = useMemo(() => {
    const c = { all: 0, draft: 0, published: 0, archived: 0 } as Record<FilterValue, number>;
    for (const course of mine.data ?? []) {
      c.all += 1;
      c[course.status] += 1;
    }
    return c;
  }, [mine.data]);

  const visible = useMemo<CourseListItem[]>(() => {
    const all = mine.data ?? [];
    return filter === "all" ? all : all.filter((c) => c.status === filter);
  }, [mine.data, filter]);

  if (!ready || !user || user.role === "student") return null;

  return (
    <div className="container mx-auto px-4 py-10">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Instructor studio</h1>
          <p className="text-muted-foreground">Manage your courses and content.</p>
        </div>
        <Link href="/studio/new">
          <Button>
            <Plus className="mr-2 h-4 w-4" /> New course
          </Button>
        </Link>
      </header>

      <div className="mb-6 flex flex-wrap gap-2" role="tablist" aria-label="Filter courses by status">
        {FILTERS.map((f) => {
          const active = filter === f.value;
          return (
            <button
              key={f.value}
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(f.value)}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm transition-colors ${
                active ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"
              }`}
            >
              {f.label}
              <span className="rounded-full bg-muted px-2 text-xs tabular-nums text-muted-foreground">
                {counts[f.value]}
              </span>
            </button>
          );
        })}
      </div>

      {mine.isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : !mine.data || mine.data.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            You haven&apos;t created any courses yet.
          </CardContent>
        </Card>
      ) : visible.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No courses in this state.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visible.map((c) => (
            <Card key={c.id}>
              <CardHeader>
                <div className="mb-1 flex items-center gap-2">
                  <Badge variant={c.status === "published" ? "default" : "muted"}>{c.status}</Badge>
                  <Badge variant="secondary">{c.subject.title}</Badge>
                </div>
                <CardTitle>
                  <Link href={`/studio/${c.id}`} className="hover:underline">
                    {c.title}
                  </Link>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex items-center justify-between text-sm text-muted-foreground">
                <span>{c.modules_count} modules</span>
                <span>{c.enrollments_count} students</span>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
