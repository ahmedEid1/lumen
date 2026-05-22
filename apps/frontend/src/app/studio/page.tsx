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
import { useT } from "@/lib/i18n/provider";
import type { MessageKey } from "@/lib/i18n/messages/en";

type FilterValue = "all" | CourseStatus;

const FILTERS: { value: FilterValue; labelKey: MessageKey }[] = [
  { value: "all", labelKey: "studio.filter.all" },
  { value: "draft", labelKey: "studio.filter.draft" },
  { value: "published", labelKey: "studio.filter.published" },
  { value: "archived", labelKey: "studio.filter.archived" },
];

export default function StudioPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();
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
    <div className="container mx-auto px-6 py-14">
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-body text-xs font-medium uppercase tracking-[0.18em] text-primary">
          {t("studio.cartouche")}
        </p>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-medium leading-tight tracking-tight sm:text-5xl">
              {t("studio.title")}
            </h1>
            <p className="mt-2 font-body text-lg text-muted-foreground">{t("studio.subtitle")}</p>
          </div>
          <Link href="/studio/new">
            <Button>
              <Plus className="me-2 h-4 w-4" /> {t("studio.newCourse")}
            </Button>
          </Link>
        </div>
      </header>

      <div
        className="mb-8 flex flex-wrap gap-2"
        role="tablist"
        aria-label={t("studio.filterAria")}
      >
        {FILTERS.map((f) => {
          const active = filter === f.value;
          return (
            <button
              key={f.value}
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(f.value)}
              className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-body transition-colors ${
                active
                  ? "border-primary/60 bg-primary/10 text-primary"
                  : "border-border/60 text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              {t(f.labelKey)}
              <span
                className={`rounded-full px-2 text-xs tabular-nums ${
                  active ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
                }`}
              >
                {counts[f.value]}
              </span>
            </button>
          );
        })}
      </div>

      {mine.isLoading ? (
        <p className="font-body text-muted-foreground">{t("common.loading")}</p>
      ) : !mine.data || mine.data.length === 0 ? (
        <Card className="surface">
          <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
            <p className="font-display text-2xl italic text-muted-foreground">
              {t("studio.empty.none")}
            </p>
            <Link href="/studio/new">
              <Button className="mt-2">
                <Plus className="me-2 h-4 w-4" /> {t("studio.newCourse")}
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : visible.length === 0 ? (
        <Card className="surface">
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <p className="font-display text-2xl italic text-muted-foreground">
              {t("studio.empty.filter")}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visible.map((c) => (
            <Card
              key={c.id}
              className="surface lift-3d transition-colors hover:border-primary/30"
            >
              <CardHeader>
                <div className="mb-1.5 flex items-center gap-2">
                  <Badge
                    className={
                      c.status === "published"
                        ? "border border-primary/40 bg-primary/10 uppercase tracking-wider text-primary"
                        : c.status === "archived"
                          ? "bg-muted text-muted-foreground uppercase tracking-wider"
                          : "bg-secondary text-secondary-foreground uppercase tracking-wider"
                    }
                  >
                    {t(`studio.filter.${c.status}` as MessageKey)}
                  </Badge>
                  <Badge variant="secondary">{c.subject.title}</Badge>
                </div>
                <CardTitle className="font-display text-xl leading-tight">
                  <Link href={`/studio/${c.id}`} className="transition-colors hover:text-primary">
                    {c.title}
                  </Link>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex items-center justify-between font-body text-sm text-muted-foreground">
                <span>{t("studio.moduleCount", { n: c.modules_count })}</span>
                <span>{t("studio.studentCount", { n: c.enrollments_count })}</span>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
