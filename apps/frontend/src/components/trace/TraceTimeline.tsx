"use client";

/**
 * Vertical timeline used by both the per-turn tutor drill-down
 * and the instructor draft replay surfaces.
 *
 * Lumen v2 Phase I4. The timeline has two modes:
 *
 *   - **Read** (default) — rows are collapsible; the first row
 *     is pre-expanded so the page reads as a clear initial
 *     state. The user clicks any row to drill in. This is the
 *     learner-facing tutor turn shape.
 *
 *   - **Replay** — an auto-advancing scrub bar steps through the
 *     rows one at a time. The active row is forced expanded with
 *     a lime accent; non-active rows stay collapsed. Pausable +
 *     scrubbable. This is the instructor-facing draft replay.
 *
 * The component is intentionally generic over the row type — it
 * takes ``TraceStep`` rows (the unified shape from
 * ``app/schemas/learner_traces.py``) so the same component
 * handles I2 multi-agent rows + I3 authoring rows + any future
 * step kind without a flag.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TraceStepCard } from "./TraceStepCard";
import type { TraceStep } from "@/lib/api/endpoints";

export interface TraceTimelineProps {
  steps: TraceStep[];
  /** Enable replay mode (auto-advance scrub bar). Default false. */
  autoPlay?: boolean;
  /** Milliseconds per step in replay mode. Default 1500. */
  stepDurationMs?: number;
  /** Override the empty-state copy. */
  emptyLabel?: string;
}

export function TraceTimeline({
  steps,
  autoPlay = false,
  stepDurationMs = 1500,
  emptyLabel = "No trace recorded.",
}: TraceTimelineProps) {
  // Replay state — the index of the currently-active step. -1
  // means "not started yet" (manual mode default), >=0 in replay
  // mode forces the matching card to render active + expanded.
  const [activeIndex, setActiveIndex] = useState(autoPlay ? 0 : -1);
  const [isPlaying, setIsPlaying] = useState(autoPlay);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset replay when the data changes.
  useEffect(() => {
    if (autoPlay) {
      setActiveIndex(0);
      setIsPlaying(true);
    }
  }, [autoPlay, steps.length]);

  // Auto-advance — schedule the next step while playing.
  useEffect(() => {
    if (!autoPlay || !isPlaying) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      return;
    }
    if (activeIndex >= steps.length - 1) {
      // Reached the end — stop the loop.
      setIsPlaying(false);
      return;
    }
    timeoutRef.current = setTimeout(() => {
      setActiveIndex((i) => Math.min(i + 1, steps.length - 1));
    }, stepDurationMs);
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [autoPlay, isPlaying, activeIndex, steps.length, stepDurationMs]);

  const togglePlay = useCallback(() => {
    if (activeIndex >= steps.length - 1 && !isPlaying) {
      // Restart from the top.
      setActiveIndex(0);
    }
    setIsPlaying((v) => !v);
  }, [activeIndex, steps.length, isPlaying]);

  const restart = useCallback(() => {
    setActiveIndex(0);
    setIsPlaying(true);
  }, []);

  const stepBack = useCallback(() => {
    setActiveIndex((i) => Math.max(0, i - 1));
    setIsPlaying(false);
  }, []);

  const stepForward = useCallback(() => {
    setActiveIndex((i) => Math.min(steps.length - 1, i + 1));
    setIsPlaying(false);
  }, [steps.length]);

  const scrubTo = useCallback((idx: number) => {
    setActiveIndex(idx);
    setIsPlaying(false);
  }, []);

  if (steps.length === 0) {
    return (
      <div
        className="surface p-6"
        data-testid="trace-timeline-empty"
      >
        <p className="font-body text-sm text-muted-foreground">
          {emptyLabel}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="trace-timeline">
      {autoPlay ? (
        <ReplayControls
          activeIndex={activeIndex}
          stepCount={steps.length}
          isPlaying={isPlaying}
          onTogglePlay={togglePlay}
          onRestart={restart}
          onStepBack={stepBack}
          onStepForward={stepForward}
          onScrub={scrubTo}
        />
      ) : null}
      <ol
        className="flex flex-col gap-2"
        aria-label="Agent trace timeline"
      >
        {steps.map((step, idx) => (
          <li key={step.trace_id} className="relative">
            {idx > 0 ? (
              <div
                className="absolute -top-2 left-3 h-2 w-px bg-border"
                aria-hidden
              />
            ) : null}
            {idx < steps.length - 1 ? (
              <div
                className="absolute -bottom-2 left-3 h-2 w-px bg-border"
                aria-hidden
              />
            ) : null}
            <TraceStepCard
              step={step}
              active={autoPlay && idx === activeIndex}
              defaultExpanded={!autoPlay && idx === 0}
            />
          </li>
        ))}
      </ol>
    </div>
  );
}

function ReplayControls({
  activeIndex,
  stepCount,
  isPlaying,
  onTogglePlay,
  onRestart,
  onStepBack,
  onStepForward,
  onScrub,
}: {
  activeIndex: number;
  stepCount: number;
  isPlaying: boolean;
  onTogglePlay: () => void;
  onRestart: () => void;
  onStepBack: () => void;
  onStepForward: () => void;
  onScrub: (idx: number) => void;
}) {
  const safeMax = Math.max(0, stepCount - 1);
  return (
    <div
      className="surface flex flex-col gap-3 p-3"
      data-testid="trace-timeline-controls"
    >
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onStepBack}
          aria-label="Previous step"
          data-testid="replay-step-back"
        >
          <SkipBack className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="default"
          size="sm"
          onClick={onTogglePlay}
          aria-label={isPlaying ? "Pause replay" : "Play replay"}
          data-testid="replay-toggle"
        >
          {isPlaying ? (
            <Pause className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Play className="h-3.5 w-3.5" aria-hidden />
          )}
          <span className="ms-1 font-mono text-[11px]">
            {isPlaying ? "Pause" : "Play"}
          </span>
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onStepForward}
          aria-label="Next step"
          data-testid="replay-step-forward"
        >
          <SkipForward className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRestart}
          aria-label="Restart replay"
          data-testid="replay-restart"
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden />
        </Button>
        <span
          className="ms-auto font-mono text-xs tabular-nums text-muted-foreground"
          data-testid="replay-position"
        >
          step {Math.min(activeIndex + 1, stepCount)} / {stepCount}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={safeMax}
        step={1}
        value={Math.min(Math.max(activeIndex, 0), safeMax)}
        onChange={(e) => onScrub(Number.parseInt(e.target.value, 10))}
        aria-label="Scrub timeline"
        data-testid="replay-scrub"
        className={cn(
          "h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted",
          "accent-primary",
        )}
      />
    </div>
  );
}
