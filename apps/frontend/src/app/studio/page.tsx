"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Download, GraduationCap, Plus, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OnboardingTour } from "@/components/onboarding/onboarding-tour";
import { AIOutlineModal } from "@/components/studio/ai-outline-modal";
import { IngestModal } from "@/components/studio/ingest-modal";
import { Courses } from "@/lib/api/endpoints";
import type { CourseListItem, CourseStatus } from "@/lib/api/types";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { instructorSteps } from "@/lib/onboarding/steps";
import { cn } from "@/lib/utils";
import type { MessageKey } from "@/lib/i18n/messages/en";

/**
 * Studio root — Workbench repaint.
 *
 * Filter tabs use `border-b-2 border-primary` for the active state (the
 * Linear / Vercel pattern), not pill chips. Courses render as bordered
 * rows — not cards — for density; the title is small and label-like,
 * meta sits in mono on the right. No `lift-3d` tilt; hover only shifts
 * the border colour.
 *
 * See docs/superpowers/specs/2026-05-22-lumen-rebuild-design.md §2.
 */

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
  const [importOpen, setImportOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);

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
      {(user.role === "instructor" || user.role === "admin") && (
        <OnboardingTour
          steps={instructorSteps(t)}
          storageKey="lumen.onboarding.instructor.dismissed"
        />
      )}
      <header className="mb-10 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("studio.cartouche")}
        </p>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
              {t("studio.title")}
            </h1>
            <p className="mt-2 font-body text-sm text-muted-foreground">{t("studio.subtitle")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => setAiOpen(true)}>
              <Sparkles className="me-2 h-4 w-4" /> {t("studio.aiOutline.button")}
            </Button>
            <Button variant="outline" onClick={() => setImportOpen(true)}>
              <Download className="me-2 h-4 w-4" /> {t("studio.import.button")}
            </Button>
            <Link href="/studio/new">
              <Button>
                <Plus className="me-2 h-4 w-4" /> {t("studio.newCourse")}
              </Button>
            </Link>
          </div>
        </div>
      </header>
      <IngestModal open={importOpen} onClose={() => setImportOpen(false)} />
      {aiOpen && <AIOutlineModal onClose={() => setAiOpen(false)} />}

      {/* Filter tabs — border-b-2 active marker, no pill chips. */}
      <Tabs
        value={filter}
        onValueChange={(v) => setFilter(v as FilterValue)}
        className="mb-6"
      >
        <TabsList
          aria-label={t("studio.filterAria")}
          className="overflow-x-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
        >
          {FILTERS.map((f) => (
            <TabsTrigger key={f.value} value={f.value}>
              <span className="font-body text-sm font-medium normal-case">
                {t(f.labelKey)}
              </span>
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {counts[f.value]}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {mine.isLoading ? (
        // Loop-5: skeleton rows that shape-match the populated list
        // shape below (`surface` block per row at ~h-16). Three rows
        // is enough to make the loading state read as "the list is
        // arriving" rather than "the page is broken".
        <div className="flex flex-col gap-2">
          <Skeleton variant="card" className="h-16" />
          <Skeleton variant="card" className="h-16" />
          <Skeleton variant="card" className="h-16" />
        </div>
      ) : !mine.data || mine.data.length === 0 ? (
        <EmptyState
          icon={GraduationCap}
          title={t("studio.empty.none")}
          cta={
            <Link href="/studio/new">
              <Button size="sm">
                <Plus className="me-2 h-4 w-4" /> {t("studio.newCourse")}
              </Button>
            </Link>
          }
        />
      ) : visible.length === 0 ? (
        <div className="surface p-8">
          <p className="font-body text-sm text-muted-foreground">{t("studio.empty.filter")}</p>
        </div>
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {visible.map((c) => (
            <li
              key={c.id}
              className="flex items-center justify-between gap-4 px-1 py-3 transition-colors duration-[160ms] hover:bg-muted/30"
            >
              <div className="flex min-w-0 flex-col gap-1">
                <Link
                  href={`/studio/${c.id}`}
                  className="font-display text-base leading-tight tracking-tight text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
                >
                  {c.title}
                </Link>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant={
                      c.status === "published"
                        ? "default"
                        : c.status === "archived"
                          ? "muted"
                          : "secondary"
                    }
                  >
                    {t(`studio.filter.${c.status}` as MessageKey)}
                  </Badge>
                  <Badge variant="outline">{c.subject.title}</Badge>
                </div>
              </div>
              <div className="hidden shrink-0 items-center gap-6 font-mono text-xs tabular-nums text-muted-foreground sm:flex">
                <span>{t("studio.moduleCount", { n: c.modules_count })}</span>
                <span>{t("studio.studentCount", { n: c.enrollments_count })}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
