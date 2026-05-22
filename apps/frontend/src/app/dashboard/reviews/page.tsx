"use client";

/**
 * Spaced-repetition review queue — Workbench surface.
 *
 * One screen, three pieces:
 *
 * 1. A header with stats (Due now / Learning / In review / Next 7
 *    days) in mono so the counts read as data rather than marketing.
 * 2. A bordered list of due cards, each linking out to the course and
 *    showing the lesson title + last-reviewed timestamp.
 * 3. An inline review surface (not a portal-modal — keeps SSR-light)
 *    that appears below the list when the learner clicks "Start
 *    review": shows the lesson title and the four grade buttons.
 *
 * Workbench rules applied:
 * - Single lime accent: the "Start review" CTA on the list rows.
 * - The four grade buttons are *outline* — none of them get the lime,
 *   because semantically Again / Hard / Good / Easy are equal-status
 *   self-reports, and tinting one would suggest a "correct" answer.
 * - Counts + timestamps in mono; lesson titles in display; copy body.
 * - Borders do the elevation work; no shadows on the cards.
 *
 * Note: we deliberately don't show the original quiz questions in the
 * review modal yet — FSRS treats the whole lesson as a single forgetting
 * curve and the learner is self-grading their memory of the lesson, not
 * re-taking the quiz. A future surface can offer "open the quiz" if the
 * learner wants to test themselves before grading.
 *
 * Rebuild Phase E4.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  ReviewsQueue,
  type ReviewCardOut,
  type ReviewRating,
} from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";

const GRADE_BUTTONS: { rating: ReviewRating; labelKey: string }[] = [
  { rating: "again", labelKey: "reviews.grade.again" },
  { rating: "hard", labelKey: "reviews.grade.hard" },
  { rating: "good", labelKey: "reviews.grade.good" },
  { rating: "easy", labelKey: "reviews.grade.easy" },
];

function formatRelative(iso: string | null, neverLabel: string, t: ReturnType<typeof useT>) {
  if (!iso) return neverLabel;
  const when = new Date(iso);
  const diffSec = Math.round((Date.now() - when.getTime()) / 1000);
  const abs = Math.abs(diffSec);
  let unit: Intl.RelativeTimeFormatUnit = "second";
  let value = diffSec;
  if (abs >= 86400) {
    unit = "day";
    value = Math.round(diffSec / 86400);
  } else if (abs >= 3600) {
    unit = "hour";
    value = Math.round(diffSec / 3600);
  } else if (abs >= 60) {
    unit = "minute";
    value = Math.round(diffSec / 60);
  }
  // negative diffSec = future; positive = past. RelativeTimeFormat
  // expects "ago" to be negative.
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  return t("reviews.lastReviewed", { when: rtf.format(-value, unit) });
}

export default function ReviewsPage() {
  const { user, ready, token } = useAuth();
  const router = useRouter();
  const t = useT();
  const qc = useQueryClient();
  const [activeCardId, setActiveCardId] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/dashboard/reviews");
  }, [ready, user, router]);

  const queueQ = useQuery({
    queryKey: qk.reviewsQueue,
    queryFn: () => ReviewsQueue.queue(token ?? undefined),
    enabled: !!user,
  });

  const statsQ = useQuery({
    queryKey: qk.reviewsStats,
    queryFn: () => ReviewsQueue.stats(token ?? undefined),
    enabled: !!user,
  });

  const gradeM = useMutation({
    mutationFn: async ({
      cardId,
      rating,
    }: {
      cardId: string;
      rating: ReviewRating;
    }) => ReviewsQueue.grade(cardId, rating, token ?? undefined),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.reviewsQueue });
      void qc.invalidateQueries({ queryKey: qk.reviewsStats });
      // Advance to the next card in the local view without waiting
      // for the refetch — the grade response itself doesn't tell us
      // which card to show next, but the new queue arrives quickly
      // and `activeCardId` clears so the list re-renders.
      setActiveCardId(null);
    },
  });

  if (!ready || !user) return null;

  const items = queueQ.data?.items ?? [];
  const stats = statsQ.data;
  const activeCard = items.find((c) => c.id === activeCardId) ?? null;

  return (
    <div className="container mx-auto px-6 py-14 sm:py-20">
      <header className="mb-12 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("reviews.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("reviews.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          {t("reviews.subtitle")}
        </p>
        {/* Cross-link to the per-learner mastery dashboard (Phase E7).
            FSRS is one half of "what should I revisit"; the mastery
            surface joins it with quiz history and tutor signals. */}
        <Link
          href="/dashboard/mastery"
          className="inline-flex items-center gap-1 self-start font-body text-sm text-primary transition-colors duration-[160ms] hover:text-primary/80"
        >
          {t("reviews.seeMastery")}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </header>

      <ReviewStats stats={stats} />

      <section className="mt-12">
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg leading-tight tracking-tight">
            {t("reviews.queueHeading")}
          </h2>
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {items.length}
          </span>
        </div>

        {queueQ.isLoading ? (
          <div className="surface h-32 animate-pulse" aria-hidden />
        ) : items.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-3">
            {items.map((card) => (
              <li key={card.id}>
                <ReviewRow
                  card={card}
                  active={card.id === activeCardId}
                  onStart={() => setActiveCardId(card.id)}
                  onGrade={(rating) =>
                    gradeM.mutate({ cardId: card.id, rating })
                  }
                  onCancel={() => setActiveCardId(null)}
                  pending={gradeM.isPending}
                  t={t}
                />
              </li>
            ))}
          </ul>
        )}

        {activeCard === null && items.length > 0 && gradeM.isSuccess && (
          <p
            className="mt-6 font-body text-sm text-muted-foreground"
            role="status"
          >
            {t("reviews.grade.allDone")}
          </p>
        )}
      </section>
    </div>
  );
}

// ---------- subcomponents ----------

function ReviewStats({
  stats,
}: {
  stats:
    | { due: number; learning: number; review: number; next_7_days: number }
    | undefined;
}) {
  const t = useT();
  const cells = [
    { key: "due", labelKey: "reviews.stats.due" as const, value: stats?.due ?? 0 },
    {
      key: "learning",
      labelKey: "reviews.stats.learning" as const,
      value: stats?.learning ?? 0,
    },
    {
      key: "review",
      labelKey: "reviews.stats.review" as const,
      value: stats?.review ?? 0,
    },
    {
      key: "next7",
      labelKey: "reviews.stats.next7" as const,
      value: stats?.next_7_days ?? 0,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cells.map((c) => (
        <div key={c.key} className="surface px-5 py-4">
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {t(c.labelKey)}
          </p>
          <p className="mt-1 font-mono text-2xl tabular-nums text-foreground">
            {c.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  const t = useT();
  return (
    <div className="surface px-5 py-10 text-center">
      <p className="font-display text-base leading-tight tracking-tight">
        {t("reviews.empty.title")}
      </p>
      <p className="mt-2 font-body text-sm text-muted-foreground">
        {t("reviews.empty.body")}
      </p>
    </div>
  );
}

function ReviewRow({
  card,
  active,
  onStart,
  onGrade,
  onCancel,
  pending,
  t,
}: {
  card: ReviewCardOut;
  active: boolean;
  onStart: () => void;
  onGrade: (rating: ReviewRating) => void;
  onCancel: () => void;
  pending: boolean;
  t: ReturnType<typeof useT>;
}) {
  const lastSeen = formatRelative(
    card.last_reviewed_at,
    t("reviews.neverReviewed"),
    t,
  );

  return (
    <article className="surface p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          <Link
            href={`/courses/${card.lesson.course_slug}`}
            className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
          >
            {card.lesson.course_title}
            <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
          <h3 className="mt-1 font-display text-base leading-tight tracking-tight text-foreground">
            {card.lesson.title}
          </h3>
          <p className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
            {lastSeen}
          </p>
        </div>

        {!active ? (
          <Button onClick={onStart} className="shrink-0">
            {t("reviews.startReview")} <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            className="shrink-0"
          >
            {t("common.cancel")}
          </Button>
        )}
      </div>

      {active && (
        <div className="mt-5 border-t border-border pt-5">
          <p className="font-body text-sm text-foreground">
            {t("reviews.grade.heading")}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {GRADE_BUTTONS.map((g) => (
              <Button
                key={g.rating}
                variant="outline"
                onClick={() => onGrade(g.rating)}
                disabled={pending}
                className="font-mono uppercase tracking-wider"
              >
                {t(g.labelKey as never)}
              </Button>
            ))}
          </div>
          <Link
            href={`/courses/${card.lesson.course_slug}`}
            className="mt-4 inline-flex items-center gap-1 font-body text-sm text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
          >
            {t("reviews.openCourse")} <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}
    </article>
  );
}
