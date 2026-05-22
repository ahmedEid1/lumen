"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { CourseCard } from "@/components/course/course-card";
import { Input } from "@/components/ui/input";
import { Catalog } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

const DIFFICULTIES: { value: string; labelKey: MessageKey }[] = [
  { value: "beginner", labelKey: "catalogPage.diff.beginner" },
  { value: "intermediate", labelKey: "catalogPage.diff.intermediate" },
  { value: "advanced", labelKey: "catalogPage.diff.advanced" },
];

export default function CatalogPage() {
  return (
    <Suspense fallback={<CatalogFallback />}>
      <CatalogInner />
    </Suspense>
  );
}

function CatalogFallback() {
  return (
    <div className="container mx-auto px-6 py-16">
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-[22rem] animate-pulse rounded-md border border-border/60 bg-card/40" />
        ))}
      </div>
    </div>
  );
}

function CatalogInner() {
  const params = useSearchParams();
  const t = useT();
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
      <section className="relative overflow-hidden border-b border-border/60 mesh-bg">
        <div className="container mx-auto flex flex-col items-center gap-5 px-6 py-24 text-center sm:py-28">
          <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
            {t("catalogPage.cartouche")}
          </p>
          <h1 className="font-display text-5xl font-medium leading-[1.05] tracking-tight sm:text-6xl">
            {t("catalogPage.h1_1")}{" "}
            <span className="italic text-shine">{t("catalogPage.h1_2")}</span>.
          </h1>
          <p className="max-w-2xl font-body text-lg text-muted-foreground">
            {t("catalogPage.subline")}
          </p>
        </div>
      </section>

      {/* Filter rail */}
      <section className="sticky top-16 z-30 border-b border-border/60 bg-background/85 backdrop-blur">
        <div className="container mx-auto flex flex-col gap-3 px-6 py-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              placeholder={t("catalogPage.searchPlaceholder")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="ps-9 font-body text-base placeholder:text-muted-foreground/70"
              aria-label={t("catalogPage.searchAria")}
            />
          </div>

          <div className="flex items-center gap-1 rounded-md border border-border/60 bg-card/40 p-1">
            <button
              type="button"
              onClick={() => setDifficulty(undefined)}
              className={cn(
                "rounded px-3 py-1.5 text-xs font-medium uppercase tracking-wider transition-colors",
                difficulty === undefined
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={difficulty === undefined}
            >
              {t("catalogPage.anyDifficulty")}
            </button>
            {DIFFICULTIES.map((d) => {
              const label = t(d.labelKey);
              return (
                <button
                  key={d.value}
                  type="button"
                  onClick={() =>
                    setDifficulty(difficulty === d.value ? undefined : d.value)
                  }
                  className={cn(
                    "rounded px-3 py-1.5 text-xs font-medium uppercase tracking-wider transition-colors",
                    difficulty === d.value
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                  aria-pressed={difficulty === d.value}
                  title={label}
                >
                  {label}
                </button>
              );
            })}
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
              className="inline-flex items-center gap-1 rounded border border-border/60 px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
            >
              <X className="h-3 w-3" /> {t("catalogPage.reset")}
            </button>
          )}
        </div>

        {/* Subject tabs */}
        {subjects.data && subjects.data.length > 0 && (
          <div className="container mx-auto flex gap-1 overflow-x-auto px-6 pb-3 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
            <button
              type="button"
              onClick={() => setSubject(undefined)}
              className={cn(
                "shrink-0 border-b-2 px-3 pb-2 text-sm font-medium transition-colors",
                subject === undefined
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={subject === undefined}
            >
              {t("catalogPage.allSubjects")}
            </button>
            {subjects.data.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSubject(subject === s.slug ? undefined : s.slug)}
                className={cn(
                  "shrink-0 border-b-2 px-3 pb-2 text-sm font-medium transition-colors",
                  subject === s.slug
                    ? "border-primary text-primary"
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

      {/* Tag chips */}
      {tags.data && tags.data.length > 0 && (
        <div
          className="container mx-auto flex flex-wrap items-center gap-2 px-6 pt-6"
          role="group"
          aria-label={t("catalogPage.tagFilterAria")}
        >
          {tag && (
            <button
              type="button"
              onClick={() => setTag(undefined)}
              className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
              aria-label={t("catalogPage.clearTagAria")}
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
                className="rounded-full border border-border/60 px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                aria-pressed={tag === t.slug}
              >
                {t.name}
              </button>
            ))}
        </div>
      )}

      {/* Grid */}
      <section className="container mx-auto px-6 py-12">
        {courses.isLoading ? (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="h-[22rem] animate-pulse rounded-md border border-border/60 bg-card/40"
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
          <div className="surface rounded-lg p-16 text-center">
            <p className="font-display text-2xl italic text-muted-foreground">
              {t("catalogPage.noMatch")}
            </p>
            <p className="mt-2 font-body text-sm text-muted-foreground">
              {t("catalogPage.noMatchBody")}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
