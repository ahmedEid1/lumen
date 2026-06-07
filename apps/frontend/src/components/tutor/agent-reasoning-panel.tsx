"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronDown, ChevronRight, Cpu, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";

/**
 * Multi-agent tutor reasoning panel (Lumen v2 Phase I2).
 *
 * Renders the per-turn plan + tool-call log under the assistant
 * message bubble. The visible "agent thinking" is what makes the
 * project legible to a recruiter in 60 seconds — this component
 * is the moat surface.
 *
 * Behaviour:
 * - "Confidence: N/5" badge sits at the top in the workbench mono
 *   face + lime accent.
 * - The plan is a tabular list (Tool | Why | Result summary).
 * - Each row expands to show the per-tool details: chunks for the
 *   retriever, snippets for the web searcher, stdout for the code
 *   runner, etc.
 * - The whole panel is collapsible (default collapsed for clean
 *   UX), but a host that wants to auto-expand the FIRST tutor turn
 *   can pass ``defaultExpanded={true}``. The ``TutorPanel`` does
 *   that for the first assistant turn on page load so a recruiter
 *   sees the agent thinking immediately.
 */
export interface ToolCallTrace {
  tool_name: string;
  args: Record<string, unknown>;
  rationale: string;
  result_summary: string;
  result_details: Record<string, unknown>;
}

export interface AgentReasoningPanelProps {
  toolCalls: ToolCallTrace[];
  confidence: number;
  /** Pre-expand the entire panel. Used for the first turn on page load. */
  defaultExpanded?: boolean;
  /**
   * When both ``conversationId`` and ``messageId`` are supplied, a
   * "See the full trace" footer link drops the learner into the
   * I4 drill-down at /dashboard/tutor/{cid}/turn/{mid}. Optional so
   * existing call sites (which render the inline panel without a
   * deep-link target) keep working.
   */
  conversationId?: string;
  messageId?: string;
}

export function AgentReasoningPanel({
  toolCalls,
  confidence,
  defaultExpanded = false,
  conversationId,
  messageId,
}: AgentReasoningPanelProps) {
  const t = useT();
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (toolCalls.length === 0) {
    // Refused / empty-retrieval turn — no plan ran, so we don't
    // even surface the disclosure. Keeps the UX quiet when there's
    // nothing to show.
    return null;
  }

  return (
    <div
      className="surface mt-2 rounded-md border border-border/60 p-3 text-sm"
      data-testid="agent-reasoning-panel"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Cpu className="h-3.5 w-3.5 text-primary" aria-hidden />
          <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {t("tutor.agentTrace.title")}
          </span>
          <ConfidenceBadge value={confidence} />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setExpanded((v) => !v)}
          aria-label={
            expanded
              ? t("tutor.agentTrace.hide")
              : t("tutor.agentTrace.show")
          }
          aria-expanded={expanded}
          data-testid="agent-trace-toggle"
        >
          {expanded ? (
            <ChevronDown className="me-1 h-3.5 w-3.5" aria-hidden />
          ) : (
            <ChevronRight className="me-1 h-3.5 w-3.5" aria-hidden />
          )}
          <span className="font-mono text-[11px]">
            {expanded
              ? t("tutor.agentTrace.hide")
              : t("tutor.agentTrace.show")}
          </span>
        </Button>
      </div>

      {expanded && (
        <div
          className="mt-3 overflow-x-auto"
          data-testid="agent-trace-rows"
        >
          <table className="w-full border-separate border-spacing-0 font-body text-xs">
            <thead>
              <tr className="text-start font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="border-b border-border/60 pb-1.5 pe-3">
                  {t("tutor.agentTrace.colTool")}
                </th>
                <th className="border-b border-border/60 pb-1.5 pe-3">
                  {t("tutor.agentTrace.colWhy")}
                </th>
                <th className="border-b border-border/60 pb-1.5 pe-3">
                  {t("tutor.agentTrace.colResult")}
                </th>
              </tr>
            </thead>
            <tbody>
              {toolCalls.map((tc, idx) => (
                <TraceRow key={`${tc.tool_name}-${idx}`} call={tc} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {/*
        I4 — "See the full trace" deep-link footer. Only rendered
        when both ids are supplied (the panel ships with optional
        props so existing call sites that don't have ids yet keep
        working). The link targets the learner-facing drill-down
        page that lays out the planner / sub-agents / retrieval
        chunks / synthesiser in one full-page view.
      */}
      {conversationId && messageId ? (
        <div
          className="mt-3 flex justify-end border-t border-border/40 pt-2"
          data-testid="agent-trace-full-link-wrap"
        >
          <Link
            href={`/dashboard/tutor/${conversationId}/turn/${messageId}`}
            className="inline-flex items-center gap-1 font-mono text-[11px] text-primary hover:underline"
            data-testid="agent-trace-full-link"
          >
            See the full trace
            <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  const t = useT();
  // 0-5 scale, capped + bounded for safety.
  const clamped = Math.max(0, Math.min(5, value));
  // Lime accent on high confidence (4-5), neutral muted otherwise.
  const isHigh = clamped >= 4;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-wider",
        isHigh
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border bg-muted text-muted-foreground",
      )}
      data-testid="agent-trace-confidence"
      aria-label={t("tutor.agentTrace.confidenceLabel", {
        n: String(clamped),
      })}
    >
      <Sparkles className="h-3 w-3" aria-hidden />
      {clamped}/5
    </span>
  );
}

function TraceRow({ call }: { call: ToolCallTrace }) {
  const t = useT();
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr
        // tabIndex/onKeyDown: the expandable row was mouse-only — a keyboard
        // user couldn't open a trace. Deliberately NOT role="button": a
        // <table> requires row children, and aria-expanded is valid on the
        // implicit row role (the expandable-row pattern).
        tabIndex={0}
        aria-expanded={open}
        className="cursor-pointer hover:bg-muted/40"
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        data-testid="agent-trace-row"
      >
        <td className="border-b border-border/40 py-2 pe-3 align-top">
          <span className="font-mono text-[11px] text-primary">
            {call.tool_name}
          </span>
        </td>
        <td className="border-b border-border/40 py-2 pe-3 align-top text-foreground/80">
          {call.rationale || (
            <span className="text-muted-foreground">
              {t("tutor.agentTrace.noRationale")}
            </span>
          )}
        </td>
        <td className="border-b border-border/40 py-2 pe-3 align-top text-foreground/80">
          {call.result_summary}
        </td>
      </tr>
      {open && (
        <tr data-testid="agent-trace-row-details">
          <td colSpan={3} className="border-b border-border/40 bg-muted/30 p-3">
            <ToolDetails call={call} />
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * Renders the per-tool details for one row.
 *
 * The five sub-agents produce different result shapes, so we
 * dispatch on ``tool_name`` to pick the right renderer. Falls
 * back to a JSON dump for unknown tools (defensive — a future
 * sub-agent that ships without a renderer update still surfaces
 * its payload rather than rendering blank).
 */
function ToolDetails({ call }: { call: ToolCallTrace }) {
  const details = call.result_details ?? {};
  if (call.tool_name === "retriever") {
    return <RetrieverDetails details={details} />;
  }
  if (call.tool_name === "web_searcher") {
    return <WebSearcherDetails details={details} />;
  }
  if (call.tool_name === "code_runner") {
    return <CodeRunnerDetails details={details} />;
  }
  if (call.tool_name === "quiz_generator") {
    return <QuizDetails details={details} />;
  }
  if (call.tool_name === "concept_explainer") {
    return <ConceptDetails details={details} />;
  }
  return (
    <pre className="overflow-x-auto rounded bg-background p-2 font-mono text-[10px] text-muted-foreground">
      {JSON.stringify(details, null, 2)}
    </pre>
  );
}

function RetrieverDetails({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const chunks = (details.chunks as Array<{
    lesson_id?: string;
    lesson_title?: string;
    text?: string;
    score?: number;
  }>) ?? [];
  if (chunks.length === 0) {
    return (
      <p className="font-mono text-[11px] text-muted-foreground">
        (no chunks retrieved)
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {chunks.map((c, i) => (
        <div
          key={`${c.lesson_id ?? "lesson"}-${i}`}
          className="rounded border border-border/40 bg-background p-2"
        >
          <div className="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
            <span className="text-primary">L:{c.lesson_id ?? "?"}</span>
            <span>·</span>
            <span>{c.lesson_title ?? ""}</span>
            <span>·</span>
            <span>score {c.score?.toFixed(3) ?? "?"}</span>
          </div>
          <p className="mt-1 whitespace-pre-wrap font-body text-[11px] text-foreground/80">
            {c.text ?? ""}
          </p>
        </div>
      ))}
    </div>
  );
}

function WebSearcherDetails({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const snippets = (details.snippets as Array<{
    title?: string;
    url?: string;
    content_first_240?: string;
  }>) ?? [];
  if (snippets.length === 0) {
    return (
      <p className="font-mono text-[11px] text-muted-foreground">
        (no snippets)
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {snippets.map((s, i) => (
        <li key={`snippet-${i}`} className="rounded border border-border/40 bg-background p-2">
          <a
            href={s.url ?? "#"}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-[11px] text-primary hover:underline"
          >
            {s.title ?? "(untitled)"}
          </a>
          <p className="mt-1 whitespace-pre-wrap font-body text-[11px] text-foreground/80">
            {s.content_first_240 ?? ""}
          </p>
        </li>
      ))}
    </ul>
  );
}

function CodeRunnerDetails({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const stdout = (details.stdout as string) ?? "";
  const exitCode = (details.exit_code as number) ?? 0;
  const errorMsg = (details.error_msg as string | null) ?? null;
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] text-muted-foreground">
        exit_code: {exitCode}
        {errorMsg ? <span> · error: {errorMsg}</span> : null}
      </div>
      <pre className="overflow-x-auto rounded bg-background p-2 font-mono text-[11px] text-foreground/80">
        {stdout || "(no stdout)"}
      </pre>
    </div>
  );
}

function QuizDetails({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const prompt = (details.prompt as string) ?? "";
  const options = (details.options as string[]) ?? [];
  const answerIndex = (details.answer_index as number) ?? 0;
  const explanation = (details.explanation as string) ?? "";
  return (
    <div className="space-y-2 font-body text-[11px]">
      <p className="font-semibold">{prompt}</p>
      <ol className="ms-4 list-decimal space-y-1">
        {options.map((opt, i) => (
          <li
            key={`opt-${i}`}
            className={cn(
              i === answerIndex ? "text-primary" : "text-foreground/80",
            )}
          >
            {opt}
            {i === answerIndex ? " ✓" : null}
          </li>
        ))}
      </ol>
      <p className="text-muted-foreground">{explanation}</p>
    </div>
  );
}

function ConceptDetails({
  details,
}: {
  details: Record<string, unknown>;
}) {
  const explanation = (details.explanation as string) ?? "";
  const analogy = (details.analogy as string | null) ?? null;
  return (
    <div className="space-y-2 font-body text-[11px] text-foreground/80">
      <p>{explanation}</p>
      {analogy ? (
        <p className="border-l-2 border-primary/40 ps-2 italic">
          {analogy}
        </p>
      ) : null}
    </div>
  );
}
