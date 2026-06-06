"use client";

import { useState } from "react";
import { Lock, ArrowLeft, Hammer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";
import type { BriefDraft, BriefLevel } from "@/lib/api/types";

/**
 * BriefReview (S3.11 / FR-DEFINE-07/16).
 *
 * The explicit review-before-build gate. The learner sees the accumulated
 * brief, can tweak the still-mutable fields (the un-finalized brief is editable,
 * FR-DEFINE-08), reads the deterministic estimate + the "a private course will
 * be created" note (FR-DEFINE-16/11), and a build starts ONLY when they press
 * the explicit confirm button (FR-DEFINE-07: never auto).
 *
 * The estimate mirrors the backend `learning_brief.estimate_counts` bands (DR-4)
 * so the count shown here is the one the orchestrator will target.
 */

/** Deterministic module estimate from the time budget — mirrors the backend
 *  `estimate_counts` bands exactly (FR-DEFINE-16 / DR-4). */
export function estimateModules(timeBudgetHours: number | null | undefined): number {
  if (!timeBudgetHours || timeBudgetHours <= 0) return 4;
  if (timeBudgetHours <= 5) return 2;
  if (timeBudgetHours <= 20) return 4;
  return 6;
}
const LESSONS_PER_MODULE = 3;

const LEVELS: BriefLevel[] = ["beginner", "intermediate", "advanced"];

interface BriefReviewProps {
  /** The accumulated brief snapshot to review (still mutable). */
  brief: BriefDraft;
  /** True while finalize+build is in flight. */
  pending: boolean;
  /** Confirm: finalize the brief (applying edits) then start the build. */
  onConfirm: (edits: BriefDraft) => void;
  /** Back to the conversation. */
  onBack: () => void;
}

export function BriefReview({ brief, pending, onConfirm, onBack }: BriefReviewProps) {
  const t = useT();
  const [goalSummary, setGoalSummary] = useState(brief.goal_summary ?? "");
  const [level, setLevel] = useState<BriefLevel | "">(
    (brief.level as BriefLevel | undefined) ?? "",
  );
  const [timeBudget, setTimeBudget] = useState(
    brief.time_budget_hours != null ? String(brief.time_budget_hours) : "",
  );
  const [sessions, setSessions] = useState(
    brief.sessions_per_week != null ? String(brief.sessions_per_week) : "",
  );

  const budgetNum = timeBudget ? Number(timeBudget) : null;
  const modules = estimateModules(budgetNum);
  const lessons = modules * LESSONS_PER_MODULE;
  const outcomes = brief.desired_outcomes ?? [];

  function buildEdits(): BriefDraft {
    return {
      goal_summary: goalSummary.trim() || null,
      level: level || null,
      time_budget_hours: budgetNum,
      sessions_per_week: sessions ? Number(sessions) : null,
    };
  }

  return (
    <section
      data-testid="brief-review"
      aria-labelledby="brief-review-heading"
      className="flex flex-col gap-6"
    >
      <header className="flex flex-col gap-2">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("define.review.cartouche")}
        </p>
        <h2
          id="brief-review-heading"
          className="font-display text-2xl leading-tight tracking-tight"
        >
          {t("define.review.title")}
        </h2>
        <p className="font-body text-sm text-muted-foreground">
          {t("define.review.subtitle")}
        </p>
      </header>

      <div className="surface flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-2">
          <label
            htmlFor="brief-goal-summary"
            className="font-body text-sm font-medium text-foreground"
          >
            {t("define.review.goalSummary")}
          </label>
          <textarea
            id="brief-goal-summary"
            value={goalSummary}
            onChange={(e) => setGoalSummary(e.target.value)}
            rows={2}
            maxLength={2000}
            className="w-full resize-y rounded-md border border-border bg-card/40 px-3 py-2 font-body text-sm text-foreground outline-none focus-visible:border-foreground/40"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div className="flex flex-col gap-2">
            <label
              htmlFor="brief-level"
              className="font-body text-sm font-medium text-foreground"
            >
              {t("define.review.level")}
            </label>
            <select
              id="brief-level"
              value={level}
              onChange={(e) => setLevel(e.target.value as BriefLevel | "")}
              className="rounded-md border border-border bg-card/40 px-3 py-2 font-body text-sm text-foreground outline-none focus-visible:border-foreground/40"
            >
              <option value="">{t("define.review.levelUnset")}</option>
              {LEVELS.map((lv) => (
                <option key={lv} value={lv}>
                  {t(`define.level.${lv}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <label
              htmlFor="brief-time-budget"
              className="font-body text-sm font-medium text-foreground"
            >
              {t("define.review.timeBudget")}
            </label>
            <input
              id="brief-time-budget"
              type="number"
              min={1}
              max={2000}
              value={timeBudget}
              onChange={(e) => setTimeBudget(e.target.value)}
              className="rounded-md border border-border bg-card/40 px-3 py-2 font-body text-sm text-foreground outline-none focus-visible:border-foreground/40"
            />
          </div>
          <div className="flex flex-col gap-2">
            <label
              htmlFor="brief-sessions"
              className="font-body text-sm font-medium text-foreground"
            >
              {t("define.review.sessions")}
            </label>
            <input
              id="brief-sessions"
              type="number"
              min={1}
              max={21}
              value={sessions}
              onChange={(e) => setSessions(e.target.value)}
              className="rounded-md border border-border bg-card/40 px-3 py-2 font-body text-sm text-foreground outline-none focus-visible:border-foreground/40"
            />
          </div>
        </div>

        {outcomes.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="font-body text-sm font-medium text-foreground">
              {t("define.review.outcomes")}
            </p>
            <ul className="list-disc ps-5 font-body text-sm text-foreground/80">
              {outcomes.map((o, i) => (
                <li key={i}>{o}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Estimate + private-course note — shown BEFORE the build (FR-DEFINE-16). */}
      <div className="surface flex flex-col gap-3 p-5">
        <p
          data-testid="build-estimate"
          className="font-body text-sm text-foreground"
        >
          {t("define.review.estimate", { modules, lessons })}
        </p>
        <p
          data-testid="private-note"
          className="flex items-start gap-2 font-body text-sm text-muted-foreground"
        >
          <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {t("define.review.privateNote")}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="default"
          disabled={pending}
          onClick={() => onConfirm(buildEdits())}
        >
          <Hammer className="me-2 h-4 w-4" aria-hidden />
          {t("define.review.build")}
        </Button>
        <Button type="button" variant="ghost" disabled={pending} onClick={onBack}>
          <ArrowLeft className="me-2 h-4 w-4" aria-hidden />
          {t("define.review.back")}
        </Button>
      </div>
    </section>
  );
}
