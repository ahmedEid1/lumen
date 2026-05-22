"use client";

/**
 * "What to do today" card — single decisive action.
 *
 * Reads ``/api/v1/me/learning-path/today``. The server returns a
 * bundle of ``{course_slug, kind, lesson_id_if_applicable,
 * due_review_count}``. We pick the loudest action:
 *
 * 1. If ``due_review_count > 0`` and the kind is
 *    ``review_due_cards`` → "Review N due cards" deep-linking to
 *    ``/dashboard/reviews``. We respect the agent's choice of
 *    "review first" because FSRS load left unattended snowballs.
 * 2. Otherwise we surface the kind-specific CTA (``start_lesson``
 *    deep-links to ``/learn/{slug}/lessons/{lesson_id}`` when the
 *    lesson id is set, falling back to the course page).
 * 3. If neither is available we render a quiet "you're caught up"
 *    state — no big card, just a single mono line.
 *
 * i18n: inline English strings (the messages file is off-limits for
 * this commit — orchestrator will extract).
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api/client";
import { pathKeys, type TodayOut } from "./types";

export function TodayWidget({ token }: { token: string | undefined }) {
  const todayQ = useQuery<TodayOut>({
    queryKey: pathKeys.today,
    queryFn: () =>
      api<TodayOut>("/api/v1/me/learning-path/today", { token }),
  });

  if (todayQ.isLoading) {
    return <div className="surface h-24 animate-pulse" aria-hidden />;
  }
  const today = todayQ.data;
  if (!today) return null;

  const dueCount = today.due_review_count;
  const kind = today.kind;
  const slug = today.course_slug;

  if (kind === "review_due_cards" || (dueCount > 0 && !kind)) {
    const plural = dueCount === 1 ? "" : "s";
    return (
      <ActionCard
        eyebrow="Today"
        title={`Review ${dueCount} due card${plural}`}
        body="Clear your spaced-repetition queue before you start anything new."
        href="/dashboard/reviews"
        ctaLabel="Open review queue"
      />
    );
  }

  if (slug && kind === "start_lesson") {
    const href = today.lesson_id_if_applicable
      ? `/learn/${slug}/lessons/${today.lesson_id_if_applicable}`
      : `/courses/${slug}`;
    const body =
      dueCount > 0
        ? `Pick up where you left off in ${slug}. You also have ${dueCount} card${dueCount === 1 ? "" : "s"} waiting to review.`
        : `Pick up where you left off in ${slug}.`;
    return (
      <ActionCard
        eyebrow="Today"
        title="Continue your path"
        body={body}
        href={href}
        ctaLabel="Open lesson"
      />
    );
  }

  if (slug && kind === "take_quiz") {
    return (
      <ActionCard
        eyebrow="Today"
        title="Take a check-in quiz"
        body={`The agent suggests testing your knowledge in ${slug}.`}
        href={`/courses/${slug}`}
        ctaLabel="Open course"
      />
    );
  }

  return (
    <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
      Nothing urgent today — keep going.
    </p>
  );
}

function ActionCard({
  eyebrow,
  title,
  body,
  href,
  ctaLabel,
}: {
  eyebrow: string;
  title: string;
  body: string;
  href: string;
  ctaLabel: string;
}) {
  return (
    <article className="surface p-6 sm:p-7">
      <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        {eyebrow}
      </p>
      <h2 className="mt-2 font-display text-xl leading-tight tracking-tight">
        {title}
      </h2>
      <p className="mt-3 font-body text-sm text-muted-foreground">{body}</p>
      <Link
        href={href}
        className="mt-5 inline-flex items-center gap-1 rounded-sm border border-primary/40 bg-primary/10 px-3 py-1.5 font-body text-sm text-primary transition-colors duration-[160ms] hover:bg-primary/15"
      >
        {ctaLabel}
        <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </article>
  );
}
