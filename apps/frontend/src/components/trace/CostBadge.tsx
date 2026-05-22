"use client";

/**
 * Top-of-page summary chip showing the totals for one agentic
 * turn or draft replay.
 *
 * Lumen v2 Phase I4. Three numbers anchor the recruiter-facing
 * "agents thinking on real money + real latency" shot:
 *
 *  - Total cost (USD), rendered with six fractional digits so a
 *    tiny Groq Llama 3.3 70B turn ("$0.000023") reads as the
 *    technical-credibility flex it is.
 *  - Total wall-clock latency (ms), tabular-nums for alignment.
 *  - Total tokens (prompt + completion combined), tabular-nums.
 *
 * Plus optional confidence and step-count badges. Every numeric
 * field uses `font-mono tabular-nums` so a long-running turn
 * with five-digit ms doesn't shift the layout.
 */

import { Activity, Coins, Cpu, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CostBadgeProps {
  /** Total cost in USD, accepts either a Decimal-string or a number. */
  costUsd: string | number;
  /** Total wall-clock latency in milliseconds. */
  latencyMs: number;
  /** Total prompt + completion tokens summed across all calls. */
  totalTokens: number;
  /** 0-5 confidence score from the planner / re-planner. Optional. */
  confidence?: number;
  /** Number of agent steps recorded for this turn / draft. Optional. */
  stepCount?: number;
  /** Override the leading label (defaults to "Agent run totals"). */
  label?: string;
  /** Extra class names for the outer surface card. */
  className?: string;
}

function formatCost(value: string | number): string {
  // Six fractional digits — sub-1¢ resolution matches the
  // ``Numeric(10, 6)`` column shape on the backend.
  const n = typeof value === "string" ? Number.parseFloat(value) : value;
  if (!Number.isFinite(n)) return "$0.000000";
  return `$${n.toFixed(6)}`;
}

function formatLatency(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0ms";
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)}s`;
  }
  return `${ms}ms`;
}

export function CostBadge({
  costUsd,
  latencyMs,
  totalTokens,
  confidence,
  stepCount,
  label = "Agent run totals",
  className,
}: CostBadgeProps) {
  const showConfidence = typeof confidence === "number";
  const isHighConfidence = showConfidence && (confidence ?? 0) >= 4;
  return (
    <div
      data-testid="trace-cost-badge"
      className={cn(
        "surface flex flex-wrap items-center gap-4 rounded-md p-4",
        className,
      )}
    >
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <div className="flex items-center gap-1.5">
        <Coins className="h-3.5 w-3.5 text-primary" aria-hidden />
        <span className="font-mono text-sm tabular-nums" data-testid="cost-value">
          {formatCost(costUsd)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <Activity className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
        <span className="font-mono text-sm tabular-nums" data-testid="latency-value">
          {formatLatency(latencyMs)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <Cpu className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
        <span className="font-mono text-sm tabular-nums" data-testid="tokens-value">
          {totalTokens.toLocaleString()} tok
        </span>
      </div>
      {showConfidence ? (
        <div
          className={cn(
            "ms-auto inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-xs tabular-nums",
            isHighConfidence
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border bg-muted text-muted-foreground",
          )}
          data-testid="confidence-value"
        >
          <Sparkles className="h-3 w-3" aria-hidden />
          <span>Confidence: {confidence}/5</span>
        </div>
      ) : null}
      {typeof stepCount === "number" ? (
        <span
          className="rounded-full border border-border bg-muted px-2.5 py-0.5 font-mono text-xs tabular-nums text-muted-foreground"
          data-testid="step-count-value"
        >
          {stepCount} step{stepCount === 1 ? "" : "s"}
        </span>
      ) : null}
    </div>
  );
}
