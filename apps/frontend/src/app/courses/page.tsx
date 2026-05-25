"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { CourseCard } from "@/components/course/course-card";
import { Button } from "@/components/ui/button";
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
    <div className="container mx-auto px-6 py-10">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="skeleton h-[18rem] border border-border"
            aria-hidden
          />
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
  const resultCount = courses.data?.total ?? courses.data?.items.length ?? 0;

  return (
    <div className="relative">
      {/* Section header — left-aligned, no marketing hero. */}
      <section className="border-b border-border">
        <div className="container mx-auto flex flex-col items-start gap-3 px-6 py-10">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("catalogPage.cartouche")}
          </p>
          <h1 className="font-display text-3xl font-medium leading-tight tracking-tight sm:text-4xl">
            {t("catalogPage.h1_1")} {t("catalogPage.h1_2")}
          </h1>
          <p className="max-w-2xl font-body text-sm text-muted-foreground">
            {t("catalogPage.subline")}
          </p>
        </div>
      </section>

      {/* Filter rail — sticky, minimal, no blur. */}
      <section className="sticky top-16 z-30 border-b border-border bg-background">
        <div className="container mx-auto flex flex-col gap-3 px-6 py-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              placeholder={t("catalogPage.searchPlaceholder")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="ps-9"
              aria-label={t("catalogPage.searchAria")}
            />
          </div>

          <div
            className="flex items-center gap-1.5"
            role="group"
            aria-label={t("catalogPage.diff.beginner")}
          >
            <Button
              type="button"
              size="sm"
              variant={difficulty === undefined ? "default" : "outline"}
              onClick={() => setDifficulty(undefined)}
              aria-pressed={difficulty === undefined}
            >
              {t("catalogPage.anyDifficulty")}
            </Button>
            {DIFFICULTIES.map((d) => {
              const label = t(d.labelKey);
              const active = difficulty === d.value;
              return (
                <Button
                  key={d.value}
                  type="button"
                  size="sm"
                  variant={active ? "default" : "outline"}
                  onClick={() => setDifficulty(active ? undefined : d.value)}
                  aria-pressed={active}
                  title={label}
                >
                  {label}
                </Button>
              );
            })}
          </div>

          {activeCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setQ("");
                setSubject(undefined);
                setDifficulty(undefined);
                setTag(undefined);
              }}
            >
              <X className="h-3.5 w-3.5" /> {t("catalogPage.reset")}
            </Button>
          )}
        </div>

        {/* Subject tabs — border-b-2 active marker. */}
        {subjects.data && subjects.data.length > 0 && (
          <div className="container mx-auto flex gap-1 overflow-x-auto px-6 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
            <button
              type="button"
              onClick={() => setSubject(undefined)}
              className={cn(
                "shrink-0 border-b-2 px-3 pb-2 pt-1 font-body text-sm font-medium transition-colors duration-[160ms]",
                subject === undefined
                  ? "border-primary text-foreground"
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
                  "shrink-0 border-b-2 px-3 pb-2 pt-1 font-body text-sm font-medium transition-colors duration-[160ms]",
                  subject === s.slug
                    ? "border-primary text-foreground"
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
              className="inline-flex items-center gap-1 rounded-md border border-primary bg-primary/10 px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-primary transition-colors duration-[160ms]"
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
                className="rounded-md border border-border px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:border-foreground hover:text-foreground"
                aria-pressed={tag === t.slug}
              >
                {t.name}
              </button>
            ))}
        </div>
      )}

      {/* Grid — compact, 3-col at lg+, gap-3, no decorative reveals. */}
      <section className="container mx-auto px-6 py-8">
        {courses.data && (
          <p className="mb-4 font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {t("catalogPage.resultCount", { count: resultCount })}
          </p>
        )}
        {courses.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="skeleton h-[18rem] border border-border"
                aria-hidden
              />
            ))}
          </div>
        ) : courses.data && courses.data.items.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {courses.data.items.map((c) => (
              <CourseCard key={c.id} course={c} />
            ))}
          </div>
        ) : (
          <div className="surface p-10 text-center">
            <p className="font-display text-xl text-foreground">
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
