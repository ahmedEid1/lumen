"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { CourseCard } from "@/components/course/course-card";
import { Input } from "@/components/ui/input";
import { Catalog } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";

export default function CatalogPage() {
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [subject, setSubject] = useState<string | undefined>(undefined);
  const [difficulty, setDifficulty] = useState<string | undefined>(undefined);
  const [tag, setTag] = useState<string | undefined>(undefined);

  useEffect(() => {
    setQ(params.get("q") ?? "");
  }, [params]);

  const subjects = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const tags = useQuery({ queryKey: qk.tags, queryFn: () => Catalog.tags() });
  const courses = useQuery({
    queryKey: qk.catalog({ q, subject, difficulty, tag }),
    queryFn: () =>
      Catalog.courses({ q, subject, difficulty, tag, page: 1, page_size: 30 }),
  });

  return (
    <div className="container mx-auto px-4 py-10">
      <header className="mb-8 flex flex-col gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Catalog</h1>
          <p className="text-muted-foreground">Find your next course.</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              placeholder="Search courses…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
              aria-label="Search courses"
            />
          </div>
          <select
            className="h-10 rounded-md border bg-background px-3 text-sm"
            value={subject ?? ""}
            onChange={(e) => setSubject(e.target.value || undefined)}
            aria-label="Filter by subject"
          >
            <option value="">All subjects</option>
            {subjects.data?.map((s) => (
              <option key={s.id} value={s.slug}>
                {s.title}
              </option>
            ))}
          </select>
          <select
            className="h-10 rounded-md border bg-background px-3 text-sm"
            value={difficulty ?? ""}
            onChange={(e) => setDifficulty(e.target.value || undefined)}
            aria-label="Filter by difficulty"
          >
            <option value="">Any difficulty</option>
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced</option>
          </select>
        </div>

        {tags.data && tags.data.length > 0 && (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Tag filter">
            {tag && (
              <button
                type="button"
                onClick={() => setTag(undefined)}
                className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                aria-label="Clear tag filter"
              >
                <X className="h-3 w-3" /> {tag}
              </button>
            )}
            {tags.data
              .filter((t) => t.slug !== tag)
              .slice(0, 20)
              .map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setTag(t.slug)}
                  className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-pressed={tag === t.slug}
                >
                  {t.name}
                </button>
              ))}
          </div>
        )}
      </header>

      {courses.isLoading ? (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-80 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      ) : courses.data && courses.data.items.length > 0 ? (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {courses.data.items.map((c) => (
            <CourseCard key={c.id} course={c} />
          ))}
        </div>
      ) : (
        <p className="rounded-lg border bg-muted/30 p-10 text-center text-muted-foreground">
          Nothing matched your filters.
        </p>
      )}
    </div>
  );
}
