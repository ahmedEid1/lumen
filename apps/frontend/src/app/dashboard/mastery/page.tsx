"use client";

/**
 * Per-learner mastery dashboard — Workbench surface.
 *
 * Rebuild Phase E7. Two stacked sections, in priority order:
 *
 * 1. "Weak spots — start here." Bordered rows, mono eyebrows, signal
 *    pills (now with lucide icons per signal — colour-only meaning
 *    was the audit's signal-severity finding), single lime CTA per
 *    row.
 *
 * 2. "Mastery per course." A row per enrolled course with two
 *    progress bars (completion = lime, mastery = info-blue so the
 *    measurements read as distinct) and the percentage in mono.
 *
 * Loop 17 polish:
 * - 2-colour bars: completion stays lime; mastery uses --info.
 * - Lucide icons on weak-spot signal pills.
 * - Shape-matching Skeleton rows replace the placeholder
 *   `<div className="h-32 animate-pulse">` blocks.
 * - Dropped the `course_id.slice(0, 12)` debug ID leak.
 *
 * Workbench rules applied: single lime accent on the actionable CTA
 * and completion fills; mono for percentages + signal text + course
 * eyebrows; borders do the lifting, no shadows.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import {
  AlertCircle,
  ArrowRight,
  Clock,
  MessageCircle,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Me } from "@/lib/api/endpoints";
import type {
  MasteryCourse,
  MasterySignal,
  MasteryWeakSpot,
} from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

// ---------- helpers ----------

function signalVariant(
  signal: MasterySignal,
): "destructive" | "warning" | "default" | "muted" {
  switch (signal) {
    case "quiz_failed":
      return "destructive";
    case "card_overdue":
      return "warning";
    case "quiz_low":
      return "default";
    case "tutor_repeat":
      return "muted";
  }
}

/** Loop 17: per-signal lucide icon so meaning isn't colour-only.
 *  Closes the audit's signal-severity finding. */
function signalIcon(signal: MasterySignal) {
  switch (signal) {
    case "quiz_failed":
      return XCircle;
    case "card_overdue":
      return Clock;
    case "quiz_low":
      return AlertCircle;
    case "tutor_repeat":
      return MessageCircle;
  }
}

function signalLabel(
  signal: MasterySignal,
  details: Record<string, string>,
  t: ReturnType<typeof useT>,
): string {
  switch (signal) {
    case "quiz_failed":
      return t("mastery.signal.quizFailed", {
        score: details.quiz_score ?? "0",
      });
    case "quiz_low":
      return t("mastery.signal.quizLow", {
        score: details.quiz_score ?? "0",
      });
    case "card_overdue":
      return t("mastery.signal.cardOverdue", {
        days: details.overdue_days ?? "0",
      });
    case "tutor_repeat":
      return t("mastery.signal.tutorRepeat", {
        count: details.tutor_count ?? "0",
      });
  }
}

// ---------- page ----------

export default function MasteryPage() {
  const { user, ready, token } = useAuth();
  const router = useRouter();
  const t = useT();

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/dashboard/mastery");
  }, [ready, user, router]);

  const masteryQ = useQuery({
    queryKey: qk.mastery,
    queryFn: () => Me.mastery(token ?? undefined),
    enabled: !!user,
  });

  if (!ready || !user) return null;

  const weakSpots = masteryQ.data?.weak_spots ?? [];
  const courses = masteryQ.data?.courses ?? [];

  return (
    <div className="container mx-auto px-6 py-14 sm:py-20">
      <header className="mb-12 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("mastery.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("mastery.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("mastery.subtitle")}
        </p>
      </header>

      <section className="mb-14">
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg leading-tight tracking-tight">
            {t("mastery.weakSpots.heading")}
          </h2>
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {weakSpots.length}
          </span>
        </div>

        {masteryQ.isLoading ? (
          <ul className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <li key={i}>
                <Skeleton variant="card" className="h-24" />
              </li>
            ))}
          </ul>
        ) : weakSpots.length === 0 ? (
          <WeakSpotsEmpty />
        ) : (
          <ul className="flex flex-col gap-3">
            {weakSpots.map((spot) => (
              <li key={spot.lesson.id}>
                <WeakSpotRow spot={spot} t={t} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg leading-tight tracking-tight">
            {t("mastery.courses.heading")}
          </h2>
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {courses.length}
          </span>
        </div>

        {masteryQ.isLoading ? (
          <ul className="flex flex-col gap-3">
            {[0, 1].map((i) => (
              <li key={i}>
                <Skeleton variant="card" className="h-28" />
              </li>
            ))}
          </ul>
        ) : courses.length === 0 ? (
          <CoursesEmpty />
        ) : (
          <ul className="flex flex-col gap-3">
            {courses.map((course) => (
              <li key={course.course_id}>
                <CourseRow course={course} t={t} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// ---------- subcomponents ----------

function WeakSpotRow({
  spot,
  t,
}: {
  spot: MasteryWeakSpot;
  t: ReturnType<typeof useT>;
}) {
  const cta = spot.review_card_id
    ? { href: "/dashboard/reviews", label: t("mastery.reviewNow") }
    : {
        href: `/courses/${spot.lesson.course_slug}`,
        label: t("mastery.openLesson"),
      };

  return (
    <article className="surface p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {spot.lesson.course_title}
          </p>
          <h3 className="mt-1 font-display text-base leading-tight tracking-tight text-foreground">
            {spot.lesson.title}
          </h3>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {spot.signals.map((signal) => {
              const Icon = signalIcon(signal);
              return (
                <Badge
                  key={signal}
                  variant={signalVariant(signal)}
                  className="inline-flex items-center gap-1"
                >
                  <Icon className="h-3 w-3" aria-hidden />
                  {signalLabel(signal, spot.signal_details, t)}
                </Badge>
              );
            })}
          </div>
        </div>
        <Link
          href={cta.href}
          className="inline-flex shrink-0 items-center gap-1 self-start rounded-sm border border-primary/40 bg-primary/10 px-3 py-1.5 font-body text-sm text-primary transition-colors duration-base hover:bg-primary/15"
        >
          {cta.label}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </article>
  );
}

function CourseRow({
  course,
  t,
}: {
  course: MasteryCourse;
  t: ReturnType<typeof useT>;
}) {
  return (
    <article className="surface p-5">
      <div className="mb-4">
        <h3 className="font-display text-base leading-tight tracking-tight">
          <Link
            href={`/courses/${course.slug}`}
            className="transition-colors duration-base hover:text-muted-foreground"
          >
            {course.title}
          </Link>
        </h3>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <CourseBar
          labelKey="mastery.courses.completion"
          value={course.completion_pct}
          t={t}
        />
        <CourseBar
          labelKey="mastery.courses.mastery"
          value={course.mastery_pct}
          t={t}
        />
      </div>
    </article>
  );
}

function CourseBar({
  labelKey,
  value,
  t,
}: {
  labelKey: "mastery.courses.completion" | "mastery.courses.mastery";
  value: number;
  t: ReturnType<typeof useT>;
}) {
  // Loop 17: completion stays lime; mastery uses --info so the two
  // bars read as distinct measurements at a glance.
  const isMastery = labelKey === "mastery.courses.mastery";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          {t(labelKey)}
        </span>
        <span
          className={cn(
            "font-mono text-xs tabular-nums",
            isMastery ? "text-info" : "text-foreground",
          )}
        >
          {value.toFixed(0)}%
        </span>
      </div>
      <Progress
        value={value}
        aria-label={t(labelKey)}
        className={isMastery ? "[&>div]:bg-info" : undefined}
      />
    </div>
  );
}

function WeakSpotsEmpty() {
  const t = useT();
  return (
    <div className="surface px-5 py-10 text-center">
      <p className="font-display text-base leading-tight tracking-tight">
        {t("mastery.weakSpots.empty.title")}
      </p>
      <p className="mt-2 font-body text-sm text-muted-foreground">
        {t("mastery.weakSpots.empty.body")}
      </p>
    </div>
  );
}

function CoursesEmpty() {
  const t = useT();
  return (
    <div className="border-t border-border px-1 py-8">
      <p className="font-body text-sm text-muted-foreground">
        {t("mastery.courses.empty")}{" "}
        <Link
          href="/courses"
          className="text-foreground underline-offset-4 transition-colors duration-base hover:underline"
        >
          {t("mastery.courses.browse")}
        </Link>
        .
      </p>
    </div>
  );
}
