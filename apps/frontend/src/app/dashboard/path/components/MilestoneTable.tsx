"use client";

/**
 * Path-steps table grouped by milestone.
 *
 * Renders the path as a series of bordered milestone groups; each
 * group has a heading (name + week range in mono) and rows for
 * the courses inside it. One row per step, showing:
 *
 *   - course slug (links to the course page) in display + line-through when completed
 *   - truncated course id in mono
 *   - status pill (pending / in_progress / completed)
 *   - "Open course" link
 *   - "Mark complete" CTA (only when ``status === "pending"``)
 *
 * The first pending row across the whole path gets a lime accent
 * stripe on the left edge — the "do this next" hint the page
 * passes in via ``highlightStepId``. Completed rows fade to
 * muted text so the eye skips over them.
 *
 * This is a client component because it carries the per-row
 * mutation for "Mark complete"; everything else is purely
 * presentational and could render server-side, but keeping the
 * component cohesive (one file = one surface) trumps that.
 *
 * i18n: inline English strings (the messages file is off-limits
 * for this commit — orchestrator will extract).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Check, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api/client";
import {
  pathKeys,
  type LearningPathStepOut,
  type StepStatus,
} from "./types";

function statusVariant(
  status: StepStatus,
): "default" | "muted" | "warning" {
  switch (status) {
    case "completed":
      return "muted";
    case "in_progress":
      return "warning";
    case "pending":
    default:
      return "default";
  }
}

function statusLabel(status: StepStatus): string {
  switch (status) {
    case "completed":
      return "Completed";
    case "in_progress":
      return "In progress";
    case "pending":
    default:
      return "Pending";
  }
}

export function MilestoneTable({
  steps,
  highlightStepId,
  token,
}: {
  steps: LearningPathStepOut[];
  highlightStepId: string | null;
  token: string | undefined;
}) {
  // Group consecutive steps by ``milestone_name``. We do this on
  // the client because the server already returns the steps in
  // ascending position order and the grouping is a render-time
  // concern only.
  const groups: { milestone: string; weeks: string; steps: LearningPathStepOut[] }[] = [];
  for (const step of steps) {
    const last = groups[groups.length - 1];
    if (last && last.milestone === step.milestone_name) {
      last.steps.push(step);
    } else {
      groups.push({
        milestone: step.milestone_name,
        weeks: step.milestone_weeks,
        steps: [step],
      });
    }
  }

  return (
    <div className="flex flex-col gap-8">
      {groups.map((group, idx) => (
        <MilestoneGroup
          key={`${group.milestone}-${idx}`}
          milestone={group.milestone}
          weeks={group.weeks}
          steps={group.steps}
          highlightStepId={highlightStepId}
          token={token}
        />
      ))}
    </div>
  );
}

function MilestoneGroup({
  milestone,
  weeks,
  steps,
  highlightStepId,
  token,
}: {
  milestone: string;
  weeks: string;
  steps: LearningPathStepOut[];
  highlightStepId: string | null;
  token: string | undefined;
}) {
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between gap-3 border-b border-border pb-2">
        <h3 className="font-display text-base leading-tight tracking-tight">
          {milestone}
        </h3>
        <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {weeks}
        </span>
      </div>
      <ul className="flex flex-col gap-2">
        {steps.map((step) => (
          <li key={step.id}>
            <StepRow
              step={step}
              highlighted={step.id === highlightStepId}
              token={token}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

function StepRow({
  step,
  highlighted,
  token,
}: {
  step: LearningPathStepOut;
  highlighted: boolean;
  token: string | undefined;
}) {
  const qc = useQueryClient();
  const completeMut = useMutation({
    mutationFn: () =>
      api<LearningPathStepOut>(
        `/api/v1/me/learning-path/steps/${step.id}/complete`,
        { method: "POST", token },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pathKeys.active });
    },
  });

  const completed = step.status === "completed";
  const accent = highlighted
    ? "border-l-2 border-l-primary"
    : "border-l-2 border-l-transparent";

  return (
    <article
      className={`surface flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between ${accent}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-3">
          <Link
            href={`/courses/${step.course_slug}`}
            className={`font-display text-base leading-tight tracking-tight transition-colors duration-[160ms] hover:text-muted-foreground ${completed ? "text-muted-foreground line-through" : ""}`}
          >
            {step.course_slug}
          </Link>
          <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {step.course_id.slice(0, 12)}
          </span>
        </div>
        <div className="mt-1.5">
          <Badge variant={statusVariant(step.status)}>
            {statusLabel(step.status)}
          </Badge>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 self-start sm:self-auto">
        {!completed && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={completeMut.isPending}
            onClick={() => completeMut.mutate()}
          >
            <Check className="mr-1 h-3.5 w-3.5" />
            {completeMut.isPending ? "Saving…" : "Mark complete"}
          </Button>
        )}
        <Link
          href={`/courses/${step.course_slug}`}
          className="inline-flex items-center gap-1 font-body text-sm text-foreground transition-colors duration-[160ms] hover:text-muted-foreground"
        >
          Open
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </article>
  );
}
