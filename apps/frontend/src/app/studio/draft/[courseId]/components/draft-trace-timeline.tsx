"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, AlertCircle, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DraftTraceStep } from "@/lib/api/endpoints";

/**
 * Vertical timeline rendering one row per CourseDraftTrace step.
 *
 * Each step is collapsible: the header shows step name + index +
 * status + duration; the expanded body renders the payload fields
 * the orchestrator captured (prompt_summary, response_summary,
 * critic_scores, weak_spots, lesson_id, etc.).
 *
 * The component is read-only and consumes the API shape exactly —
 * no derivation that would diverge between client and server.
 */

const STEP_LABELS: Record<string, string> = {
  researcher: "Researcher",
  outliner: "Outliner",
  critic: "Critic",
  reviser: "Reviser",
  lesson_drafter: "Lesson drafter",
  final_critic: "Final critic",
};

function formatStepLabel(step: string): string {
  return STEP_LABELS[step] ?? step;
}

interface TraceTimelineProps {
  steps: DraftTraceStep[];
}

export function DraftTraceTimeline({ steps }: TraceTimelineProps) {
  if (steps.length === 0) {
    return (
      <div className="surface flex flex-col items-start gap-2 p-6">
        <p className="font-body text-sm text-muted-foreground">
          No trace recorded for this course yet.
        </p>
      </div>
    );
  }
  return (
    <ol className="flex flex-col gap-2" data-testid="draft-trace-timeline">
      {steps.map((step, idx) => (
        <TraceRow
          key={step.id}
          step={step}
          isFirst={idx === 0}
          isLast={idx === steps.length - 1}
        />
      ))}
    </ol>
  );
}

function TraceRow({
  step,
  isFirst,
  isLast,
}: {
  step: DraftTraceStep;
  isFirst: boolean;
  isLast: boolean;
}) {
  const [open, setOpen] = useState(false);
  const isError = step.status === "error";
  return (
    <li
      data-testid={`draft-trace-step-${step.step}`}
      data-step={step.step}
      data-step-index={step.step_index}
      className="relative"
    >
      {/* Connector line between rows — purely decorative. */}
      {!isFirst && (
        <div className="absolute -top-2 start-3 h-2 w-px bg-border" aria-hidden />
      )}
      {!isLast && (
        <div className="absolute -bottom-2 start-3 h-2 w-px bg-border" aria-hidden />
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={`draft-trace-step-body-${step.id}`}
        className={cn(
          "group flex w-full items-center gap-3 rounded-md border border-border bg-card/40 px-3 py-2 text-start transition-colors duration-[160ms]",
          isError ? "hover:bg-destructive/5" : "hover:bg-muted/40",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-[10px] tabular-nums",
            isError
              ? "bg-destructive/10 text-destructive"
              : "bg-muted text-muted-foreground",
          )}
        >
          {step.step_index}
        </span>
        {isError ? (
          <AlertCircle
            className="h-4 w-4 shrink-0 text-destructive"
            aria-hidden
          />
        ) : (
          <CheckCircle2
            className="h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden
          />
        )}
        <span className="font-display text-sm leading-tight text-foreground">
          {formatStepLabel(step.step)}
        </span>
        <div className="ms-auto flex items-center gap-2 font-mono text-xs tabular-nums text-muted-foreground">
          {step.duration_ms > 0 && <span>{step.duration_ms}ms</span>}
          {isError && <Badge variant="destructive">error</Badge>}
          {open ? (
            <ChevronDown className="h-4 w-4" aria-hidden />
          ) : (
            <ChevronRight className="h-4 w-4" aria-hidden />
          )}
        </div>
      </button>
      {open && (
        <div
          id={`draft-trace-step-body-${step.id}`}
          className="ms-9 mt-2 flex flex-col gap-2 rounded-md border border-border bg-card/20 p-3 font-mono text-xs text-muted-foreground"
        >
          <PayloadRenderer payload={step.payload} />
        </div>
      )}
    </li>
  );
}

function PayloadRenderer({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const prompt = String(payload.prompt_summary ?? "");
  const response = String(payload.response_summary ?? "");
  const error = payload.error ? String(payload.error) : null;
  const scores = payload.critic_scores as
    | { coverage?: number; learning_arc?: number; scope?: number }
    | undefined;
  const weakSpots = Array.isArray(payload.weak_spots)
    ? (payload.weak_spots as string[])
    : [];
  const lessonId = payload.lesson_id ? String(payload.lesson_id) : null;
  const revisionNumber =
    typeof payload.revision_number === "number"
      ? (payload.revision_number as number)
      : null;
  return (
    <>
      {prompt && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Prompt
          </p>
          <p className="whitespace-pre-wrap text-foreground/80">{prompt}</p>
        </div>
      )}
      {response && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Response
          </p>
          <p className="whitespace-pre-wrap text-foreground/80">{response}</p>
        </div>
      )}
      {scores && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Scores
          </p>
          <p className="text-foreground/80 tabular-nums">
            coverage {scores.coverage} · arc {scores.learning_arc} · scope{" "}
            {scores.scope}
          </p>
        </div>
      )}
      {weakSpots.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Weak spots
          </p>
          <ul className="list-disc ps-4 text-foreground/80">
            {weakSpots.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
      {lessonId && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Lesson id
          </p>
          <p className="text-foreground/80">{lessonId}</p>
        </div>
      )}
      {revisionNumber !== null && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Revision number
          </p>
          <p className="text-foreground/80 tabular-nums">{revisionNumber}</p>
        </div>
      )}
      {error && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-destructive">
            Error
          </p>
          <p className="whitespace-pre-wrap text-destructive">{error}</p>
        </div>
      )}
    </>
  );
}

export interface FinalScore {
  coverage: number;
  learning_arc: number;
  scope: number;
  mean: number;
  rationale: string;
}

export function FinalScoreBadge({ score }: { score: FinalScore }) {
  // Mean ≥4 → electric-lime; 3-3.99 → amber; <3 → red. The tokens
  // map to the existing Workbench palette: `bg-primary` is the
  // electric-lime accent; muted greens/ambers fall back to the
  // shadcn defaults below. Keep the colour logic visible (data
  // attributes + tailwind classes) so designers can re-skin.
  const variant: "good" | "warn" | "bad" =
    score.mean >= 4 ? "good" : score.mean >= 3 ? "warn" : "bad";
  return (
    <div
      data-testid="draft-trace-final-score"
      data-variant={variant}
      className={cn(
        "surface flex flex-col gap-2 p-4",
        variant === "good" && "border-primary/40",
        variant === "warn" && "border-amber-500/40",
        variant === "bad" && "border-destructive/40",
      )}
    >
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        Final critic score
      </p>
      <p className="font-display text-3xl tabular-nums">
        {score.mean.toFixed(2)}
        <span className="text-base text-muted-foreground"> / 5</span>
      </p>
      <p className="font-mono text-xs tabular-nums text-muted-foreground">
        coverage {score.coverage} · arc {score.learning_arc} · scope{" "}
        {score.scope}
      </p>
      {score.rationale && (
        <p className="mt-1 font-body text-sm text-foreground/80">
          {score.rationale}
        </p>
      )}
    </div>
  );
}

export function PublishAnywayButton({
  onClick,
  disabled,
}: {
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid="publish-anyway-button"
      variant="default"
    >
      Publish anyway
    </Button>
  );
}
