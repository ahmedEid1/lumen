"use client";

/**
 * One collapsible step in a trace timeline.
 *
 * Lumen v2 Phase I4. Each TraceStepCard is the smallest unit of
 * the "show your work" surface — a step header (step kind +
 * step_index + duration + status) and a body that renders the
 * structured payload appropriately for the step kind:
 *
 *   - "plan" / "replan"           → tool_calls list + confidence
 *   - "tool_call" / "sub_agent.*" → tool_name + rationale +
 *                                    structured details
 *   - retriever chunks            → RetrievalChunkList
 *   - "synthesis"                 → answer head + citation count
 *   - I3 authoring steps          → prompt / response summaries,
 *                                    critic scores, weak spots
 *   - Anything else               → pretty-printed JSON
 *
 * The card supports two interaction modes:
 *
 *   - **manual** — user clicks the header to toggle (default).
 *   - **active** — when the parent is in auto-play replay mode,
 *     the active step is forced expanded with the lime accent;
 *     all other steps stay collapsed. The parent passes
 *     ``active=true`` for one card at a time and ``expanded``
 *     overrides the local state.
 */

import { useState } from "react";
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { RetrievalChunkList } from "./RetrievalChunkList";
import type { TraceStep } from "@/lib/api/endpoints";

// Friendly labels for the open-ended ``step`` string. Falls back
// to the raw value (which is fine — it's already snake_case +
// human-readable).
const STEP_LABELS: Record<string, string> = {
  plan: "Planner",
  replan: "Re-planner",
  tool_call: "Tool call",
  "tool_call.error": "Tool call (error)",
  synthesis: "Synthesiser",
  "sub_agent.retriever": "Retriever",
  "sub_agent.web_searcher": "Web searcher",
  "sub_agent.code_runner": "Code runner",
  "sub_agent.quiz_generator": "Quiz generator",
  "sub_agent.concept_explainer": "Concept explainer",
  researcher: "Researcher",
  outliner: "Outliner",
  critic: "Critic",
  reviser: "Reviser",
  lesson_drafter: "Lesson drafter",
  final_critic: "Final critic",
};

function labelFor(step: string): string {
  return STEP_LABELS[step] ?? step;
}

export interface TraceStepCardProps {
  step: TraceStep;
  /** When true, the card is forced expanded + lime-accented. */
  active?: boolean;
  /** Initial expansion in manual mode. Ignored when ``active`` is set. */
  defaultExpanded?: boolean;
  /** Called when the user toggles the disclosure (manual mode only). */
  onToggle?: (open: boolean) => void;
}

export function TraceStepCard({
  step,
  active = false,
  defaultExpanded = false,
  onToggle,
}: TraceStepCardProps) {
  const [internalOpen, setInternalOpen] = useState(defaultExpanded);
  const open = active || internalOpen;
  const isError = step.status === "error";

  return (
    <article
      data-testid={`trace-step-${step.step}`}
      data-step={step.step}
      data-step-index={step.step_index}
      data-active={active ? "true" : "false"}
      className={cn(
        "rounded-md border bg-card/40 transition-colors duration-[160ms]",
        active
          ? "border-primary/60 bg-primary/5 shadow-[0_0_0_1px_hsl(var(--primary)/0.3)]"
          : "border-border",
      )}
    >
      <button
        type="button"
        onClick={() => {
          if (active) return;
          const next = !internalOpen;
          setInternalOpen(next);
          onToggle?.(next);
        }}
        aria-expanded={open}
        aria-controls={`trace-step-body-${step.trace_id}`}
        className={cn(
          "group flex w-full items-center gap-3 px-3 py-2 text-left",
          isError ? "hover:bg-destructive/5" : "hover:bg-muted/40",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-[10px] tabular-nums",
            active
              ? "bg-primary/20 text-primary"
              : isError
                ? "bg-destructive/10 text-destructive"
                : "bg-muted text-muted-foreground",
          )}
        >
          {step.step_index}
        </span>
        {isError ? (
          <AlertCircle className="h-4 w-4 shrink-0 text-destructive" aria-hidden />
        ) : (
          <CheckCircle2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        )}
        <span className="font-display text-sm leading-tight text-foreground">
          {labelFor(step.step)}
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
      {open ? (
        <div
          id={`trace-step-body-${step.trace_id}`}
          className="border-t border-border/60 p-3"
        >
          <PayloadBody step={step} />
        </div>
      ) : null}
    </article>
  );
}

function PayloadBody({ step }: { step: TraceStep }) {
  const payload = step.payload ?? {};
  switch (step.step) {
    case "plan":
    case "replan":
      return <PlanPayload payload={payload} />;
    case "tool_call":
    case "tool_call.error":
      return <ToolCallPayload payload={payload} />;
    case "sub_agent.retriever":
      return <RetrieverPayload payload={payload} />;
    case "synthesis":
      return <SynthesisPayload payload={payload} />;
    case "researcher":
    case "outliner":
    case "critic":
    case "reviser":
    case "lesson_drafter":
    case "final_critic":
      return <AuthoringPayload payload={payload} />;
    default:
      return <FallbackPayload payload={payload} />;
  }
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="font-body text-xs text-foreground/85">{children}</div>
    </div>
  );
}

function PlanPayload({ payload }: { payload: Record<string, unknown> }) {
  const toolCalls = (payload.tool_calls as
    | Array<{ tool_name?: string; rationale?: string }>
    | undefined) ?? [];
  const confidence = payload.confidence_after_plan as number | undefined;
  const hint = payload.final_answer_hint as string | null | undefined;
  const decoded = payload.decoded as
    | { needs_more?: boolean; confidence_now?: number }
    | undefined;
  const replanConfidence = decoded?.confidence_now;
  return (
    <div className="flex flex-col gap-3">
      {typeof confidence === "number" ? (
        <Section label="Confidence">
          <span className="font-mono tabular-nums">{confidence}/5</span>
        </Section>
      ) : null}
      {typeof replanConfidence === "number" ? (
        <Section label="Re-plan confidence">
          <span className="font-mono tabular-nums">{replanConfidence}/5</span>
        </Section>
      ) : null}
      {toolCalls.length > 0 ? (
        <Section label="Tool calls">
          <ul className="flex flex-col gap-1">
            {toolCalls.map((tc, i) => (
              <li key={i} className="flex items-baseline gap-2">
                <span className="font-mono text-[11px] text-primary">
                  {tc.tool_name ?? "?"}
                </span>
                <span className="text-foreground/70">
                  {tc.rationale ?? ""}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
      {hint ? (
        <Section label="Synth hint">
          <p className="whitespace-pre-wrap">{hint}</p>
        </Section>
      ) : null}
    </div>
  );
}

function ToolCallPayload({ payload }: { payload: Record<string, unknown> }) {
  const toolName = payload.tool_name as string | undefined;
  const rationale = payload.rationale as string | undefined;
  const args = payload.args as Record<string, unknown> | undefined;
  const errorKind = payload.error_kind as string | undefined;
  return (
    <div className="flex flex-col gap-3">
      {toolName ? (
        <Section label="Tool">
          <span className="font-mono text-primary">{toolName}</span>
        </Section>
      ) : null}
      {rationale ? (
        <Section label="Why">
          <p className="whitespace-pre-wrap">{rationale}</p>
        </Section>
      ) : null}
      {args && Object.keys(args).length > 0 ? (
        <Section label="Args">
          <pre className="overflow-x-auto rounded bg-background p-2 font-mono text-[11px] text-foreground/80">
            {JSON.stringify(args, null, 2)}
          </pre>
        </Section>
      ) : null}
      {errorKind ? (
        <Section label="Error">
          <span className="font-mono text-destructive">{errorKind}</span>
        </Section>
      ) : null}
    </div>
  );
}

function RetrieverPayload({ payload }: { payload: Record<string, unknown> }) {
  const chunks = (payload.chunks as Array<Record<string, unknown>>) ?? [];
  const query = payload.query as string | undefined;
  return (
    <div className="flex flex-col gap-3">
      {query ? (
        <Section label="Query">
          <span className="font-mono">{query}</span>
        </Section>
      ) : null}
      <Section label="Retrieved chunks">
        <RetrievalChunkList chunks={chunks as never} />
      </Section>
    </div>
  );
}

function SynthesisPayload({ payload }: { payload: Record<string, unknown> }) {
  const answerHead = payload.answer_head as string | undefined;
  const citationCount = payload.citation_count as number | undefined;
  const toolCallsInSynth = payload.tool_calls_in_synth as number | undefined;
  return (
    <div className="flex flex-col gap-3">
      {answerHead ? (
        <Section label="Answer (head)">
          <p className="whitespace-pre-wrap">{answerHead}</p>
        </Section>
      ) : null}
      {typeof citationCount === "number" ? (
        <Section label="Citations">
          <span className="font-mono tabular-nums">{citationCount}</span>
        </Section>
      ) : null}
      {typeof toolCallsInSynth === "number" ? (
        <Section label="Tool results folded in">
          <span className="font-mono tabular-nums">{toolCallsInSynth}</span>
        </Section>
      ) : null}
    </div>
  );
}

function AuthoringPayload({ payload }: { payload: Record<string, unknown> }) {
  const prompt = payload.prompt_summary as string | undefined;
  const response = payload.response_summary as string | undefined;
  const scores = payload.critic_scores as
    | { coverage?: number; learning_arc?: number; scope?: number }
    | undefined;
  const weakSpots = Array.isArray(payload.weak_spots)
    ? (payload.weak_spots as string[])
    : [];
  const lessonId = payload.lesson_id as string | undefined;
  const revisionNumber = payload.revision_number as number | undefined;
  return (
    <div className="flex flex-col gap-3">
      {prompt ? (
        <Section label="Prompt">
          <p className="whitespace-pre-wrap">{prompt}</p>
        </Section>
      ) : null}
      {response ? (
        <Section label="Response">
          <p className="whitespace-pre-wrap">{response}</p>
        </Section>
      ) : null}
      {scores ? (
        <Section label="Scores">
          <p className="font-mono tabular-nums">
            coverage {scores.coverage} · arc {scores.learning_arc} · scope{" "}
            {scores.scope}
          </p>
        </Section>
      ) : null}
      {weakSpots.length > 0 ? (
        <Section label="Weak spots">
          <ul className="list-disc ps-4">
            {weakSpots.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Section>
      ) : null}
      {lessonId ? (
        <Section label="Lesson id">
          <span className="font-mono">{lessonId}</span>
        </Section>
      ) : null}
      {typeof revisionNumber === "number" ? (
        <Section label="Revision #">
          <span className="font-mono tabular-nums">{revisionNumber}</span>
        </Section>
      ) : null}
    </div>
  );
}

function FallbackPayload({ payload }: { payload: Record<string, unknown> }) {
  if (Object.keys(payload).length === 0) {
    return (
      <p className="font-mono text-xs text-muted-foreground">
        (no payload recorded)
      </p>
    );
  }
  return (
    <pre className="overflow-x-auto rounded bg-background p-2 font-mono text-[11px] text-foreground/80">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}
