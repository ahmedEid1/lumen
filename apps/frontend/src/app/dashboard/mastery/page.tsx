"use client";

/**
 * Per-learner mastery dashboard — Workbench surface.
 *
 * Rebuild Phase E7. Two stacked sections, in priority order:
 *
 * 1. "Weak spots — start here." Bordered rows, mono eyebrows, signal
 *    pills, single lime CTA per row. The list is the actionable bit
 *    of the page — a learner with three failed quizzes and a stale
 *    FSRS card should see them all at a glance and pick one to
 *    address. We list lessons, not courses, because the unit of
 *    "thing I can revisit right now" is a lesson.
 *
 * 2. "Mastery per course." A row per enrolled course with two thin
 *    progress bars (completion + mastery) and the percentage in mono.
 *    No CTAs in this section — the row title links into the course,
 *    that's it; clicking somewhere else on the row would be a fake
 *    affordance.
 *
 * Workbench rules applied:
 * - Single lime accent: the "Review now" CTAs in the weak-spots list
 *   and the lime progress fills under "Mastery per course".
 * - Mono for percentages, signal badge text, lesson ids, course
 *   eyebrows. Display for lesson titles + section headings. Body for
 *   subtitle/empty-state copy.
 * - Borders do the lifting; no shadows on rows.
 * - "Mastery" and "Completion" bars get the same visual treatment
 *   (no second accent for mastery) because the dashboard is not
 *   trying to rank them — the learner reads both side-by-side.
 *
 * Note: the page bundles the API into a single fetch
 * (``Me.mastery()``) so the surface paints both sections on one
 * loading state. Splitting would mean either a flash between two
 * loading rectangles or an awkward "wait for both before rendering"
 * dance.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Me } from "@/lib/api/endpoints";
import type {
  MasteryCourse,
  MasterySignal,
  MasteryWeakSpot,
} from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

// ---------- helpers ----------

/** Pick a Badge variant per signal code. ``quiz_failed`` is the
 *  loudest (destructive); the others sit somewhere between info
 *  and muted so the row doesn't read like a christmas tree. */
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

/** Build the user-facing pill text for one signal + the numeric
 *  context the service attached. We deliberately don't pre-compose
 *  on the server — i18n lives here, the API ships raw values. */
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
          <div className="surface h-32 animate-pulse" aria-hidden />
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
          <div className="surface h-32 animate-pulse" aria-hidden />
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
  // If the FSRS queue has a card for this lesson, the "Review now"
  // CTA deep-links into the spaced-repetition surface where the
  // learner can grade and recover the schedule. Otherwise the CTA
  // opens the course detail so the learner can revisit the lesson
  // directly — there's no specific card to surface.
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
            {spot.signals.map((signal) => (
              <Badge key={signal} variant={signalVariant(signal)}>
                {signalLabel(signal, spot.signal_details, t)}
              </Badge>
            ))}
          </div>
        </div>
        <Link
          href={cta.href}
          className="inline-flex shrink-0 items-center gap-1 self-start rounded-sm border border-primary/40 bg-primary/10 px-3 py-1.5 font-body text-sm text-primary transition-colors duration-[160ms] hover:bg-primary/15"
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
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h3 className="font-display text-base leading-tight tracking-tight">
          <Link
            href={`/courses/${course.slug}`}
            className="transition-colors duration-[160ms] hover:text-muted-foreground"
          >
            {course.title}
          </Link>
        </h3>
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          {course.course_id.slice(0, 12)}
        </span>
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
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          {t(labelKey)}
        </span>
        <span className="font-mono text-xs tabular-nums text-foreground">
          {value.toFixed(0)}%
        </span>
      </div>
      <Progress value={value} aria-label={t(labelKey)} />
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
          className="text-foreground underline-offset-4 transition-colors duration-[160ms] hover:underline"
        >
          {t("mastery.courses.browse")}
        </Link>
        .
      </p>
    </div>
  );
}
