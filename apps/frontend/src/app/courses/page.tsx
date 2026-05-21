"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { CourseCard } from "@/components/course/course-card";
import { Input } from "@/components/ui/input";
import { Cartouche } from "@/components/lumen/cartouche";
import { Glyph } from "@/components/lumen/glyph";
import { PapyrusBg } from "@/components/lumen/papyrus-bg";
import { Catalog } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";

const DIFFICULTIES = [
  { value: "beginner", label: "Initiate" },
  { value: "intermediate", label: "Scribe" },
  { value: "advanced", label: "High Priest" },
] as const;

export default function CatalogPage() {
  return (
    <Suspense fallback={<CatalogFallback />}>
      <CatalogInner />
    </Suspense>
  );
}

function CatalogFallback() {
  return (
    <div className="container mx-auto px-4 py-16">
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-[22rem] animate-pulse rounded-md border border-border bg-card/40" />
        ))}
      </div>
    </div>
  );
}

function CatalogInner() {
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [subject, setSubject] = useState<string | undefined>(params.get("subject") ?? undefined);
  const [difficulty, setDifficulty] = useState<string | undefined>(
    params.get("difficulty") ?? undefined,
  );
  const [tag, setTag] = useState<string | undefined>(params.get("tag") ?? undefined);

  useEffect(() => {
    setQ(params.get("q") ?? "");
    setSubject(params.get("subject") ?? undefined);
    setDifficulty(params.get("difficulty") ?? undefined);
    setTag(params.get("tag") ?? undefined);
  }, [params]);

  const subjects = useQuery({ queryKey: qk.subjects, queryFn: () => Catalog.subjects() });
  const tags = useQuery({ queryKey: qk.tags, queryFn: () => Catalog.tags() });
  const courses = useQuery({
    queryKey: qk.catalog({ q, subject, difficulty, tag }),
    queryFn: () => Catalog.courses({ q, subject, difficulty, tag, page: 1, page_size: 30 }),
  });

  const activeCount = [q, subject, difficulty, tag].filter(Boolean).length;

  return (
    <div className="relative">
      {/* Page header strip */}
      <section className="relative overflow-hidden border-b border-gold/15">
        <PapyrusBg />
        <div className="container mx-auto flex flex-col items-center gap-5 px-4 py-20 text-center">
          <Cartouche>The scroll room</Cartouche>
          <h1
            className="font-display text-5xl font-medium leading-tight tracking-tight sm:text-6xl"
            style={{ fontVariationSettings: '"opsz" 144, "SOFT" 25' }}
          >
            Every discipline, <span className="italic text-gold-gradient">catalogued</span>.
          </h1>
          <p className="max-w-2xl font-body text-lg text-muted-foreground">
            Browse what scribes across the temple are teaching. Filter by subject, difficulty, or
            the mark of a tag.
          </p>
        </div>
      </section>

      {/* Filter rail */}
      <section className="sticky top-16 z-30 border-b border-gold/15 bg-background/85 backdrop-blur">
        <div className="container mx-auto flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gold/60"
              aria-hidden
            />
            <Input
              placeholder="Search the scroll room…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="border-gold/25 bg-card/60 ps-9 font-body text-base placeholder:italic placeholder:text-muted-foreground/70 focus-visible:border-gold/60"
              aria-label="Search courses"
            />
          </div>

          <div className="flex items-center gap-1 rounded-md border border-gold/20 bg-card/40 p-1">
            <button
              type="button"
              onClick={() => setDifficulty(undefined)}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-medium uppercase tracking-wider transition-colors",
                difficulty === undefined
                  ? "bg-gold/15 text-gold"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={difficulty === undefined}
            >
              Any
            </button>
            {DIFFICULTIES.map((d, i) => (
              <button
                key={d.value}
                type="button"
                onClick={() =>
                  setDifficulty(difficulty === d.value ? undefined : d.value)
                }
                className={cn(
                  "flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium uppercase tracking-wider transition-colors",
                  difficulty === d.value
                    ? "bg-gold/15 text-gold"
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-pressed={difficulty === d.value}
                title={d.label}
              >
                {Array.from({ length: i + 1 }).map((_, k) => (
                  <Glyph key={k} name="ankh" size={11} />
                ))}
                <span>{d.label}</span>
              </button>
            ))}
          </div>

          {activeCount > 0 && (
            <button
              type="button"
              onClick={() => {
                setQ("");
                setSubject(undefined);
                setDifficulty(undefined);
                setTag(undefined);
              }}
              className="inline-flex items-center gap-1 rounded border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:border-gold/40 hover:text-gold"
            >
              <X className="h-3 w-3" /> Reset
            </button>
          )}
        </div>

        {/* Subjects as papyrus tabs */}
        {subjects.data && subjects.data.length > 0 && (
          <div className="container mx-auto flex gap-1 overflow-x-auto px-4 pb-3 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
            <button
              type="button"
              onClick={() => setSubject(undefined)}
              className={cn(
                "shrink-0 border-b-2 px-3 pb-2 text-sm font-medium transition-colors",
                subject === undefined
                  ? "border-gold text-gold"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={subject === undefined}
            >
              All
            </button>
            {subjects.data.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSubject(subject === s.slug ? undefined : s.slug)}
                className={cn(
                  "shrink-0 border-b-2 px-3 pb-2 text-sm font-medium transition-colors",
                  subject === s.slug
                    ? "border-gold text-gold"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
                aria-pressed={subject === s.slug}
              >
                {s.title}
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Tag seals */}
      {tags.data && tags.data.length > 0 && (
        <div className="container mx-auto flex flex-wrap items-center gap-2 px-4 pt-6" role="group" aria-label="Tag filter">
          {tag && (
            <button
              type="button"
              onClick={() => setTag(undefined)}
              className="inline-flex items-center gap-1 rounded-full border border-gold/40 bg-gold/10 px-3 py-1 text-xs font-medium text-gold"
              aria-label="Clear tag filter"
            >
              <X className="h-3 w-3" /> {tag}
            </button>
          )}
          {tags.data
            .filter((t) => t.slug !== tag)
            .slice(0, 24)
            .map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTag(t.slug)}
                className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-gold/40 hover:text-gold"
                aria-pressed={tag === t.slug}
              >
                {t.name}
              </button>
            ))}
        </div>
      )}

      {/* Grid */}
      <section className="container mx-auto px-4 py-10">
        {courses.isLoading ? (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-[22rem] animate-pulse rounded-md border border-border bg-card/40"
              />
            ))}
          </div>
        ) : courses.data && courses.data.items.length > 0 ? (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {courses.data.items.map((c, i) => (
              <div key={c.id} className="reveal" style={{ animationDelay: `${(i % 6) * 50}ms` }}>
                <CourseCard course={c} />
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-gold/30 bg-card/40 p-16 text-center scroll-paper">
            <Glyph name="feather" size={48} className="mx-auto mb-4 text-gold/40" />
            <p className="font-display text-xl italic text-muted-foreground">
              No scrolls match those filters.
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Try fewer constraints, or reset the search.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
