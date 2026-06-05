"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Loader2, AlertTriangle, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AI, Courses, Define } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useT } from "@/lib/i18n/provider";
import { DraftTraceTimeline } from "@/app/studio/draft/[courseId]/components/draft-trace-timeline";
import type { DraftFromBriefResponse } from "@/lib/api/types";

/**
 * BuildProgress (S3.11 / FR-DEFINE-17).
 *
 * Renders the self-serve build's progress by REUSING the CourseDraftTrace
 * timeline (`DraftTraceTimeline`), the same surface `/studio/draft/[courseId]`
 * renders, so the reasoning trace looks identical wherever it appears. The
 * build endpoint is synchronous server-side (it returns once the pipeline
 * lands), so by the time we have a `result` the trace is already complete; we
 * still poll the trace + course status briefly so a slow commit settles before
 * we offer the learn deep-link.
 *
 * Three terminal surfaces:
 *  - building : spinner + (once available) the trace timeline.
 *  - success  : the trace + a deep-link into the owner self-learn surface
 *               (`/learn/[slug]`) — define → build → LEARN.
 *  - failed   : a clean build_failed surface (no half-course) + a retry that
 *               re-runs the idempotent build (FR-DEFINE-13).
 */

type Phase = "building" | "success" | "failed";

interface BuildProgressProps {
  phase: Phase;
  /** The build result once the pipeline lands (carries the slug deep-link). */
  result: DraftFromBriefResponse | null;
  /** The finalized brief id — polled while building to obtain the in-flight
   *  shell's course id (the cancel target) before the build endpoint returns. */
  briefId: string | null;
  /** A normalized failure message when phase === "failed". */
  error: string | null;
  /** Re-run the (idempotent) build. */
  onRetry: () => void;
  /** Cancel an in-flight build → flips the course to build_failed. Receives the
   *  resolved course id (polled shell id while building, result id once landed). */
  onCancel: (courseId: string) => void;
  /** A server-side flip to build_failed (e.g. cancel from another tab) surfaced
   *  by the poll while building — drives the page to its failed terminal state. */
  onTerminalFailure: (message: string) => void;
  /** True while a retry mutation is in flight (gates the retry button). */
  busy: boolean;
  /** True while a CANCEL mutation is in flight (gates the cancel button only —
   *  it must NOT be gated by the in-flight build, which is exactly when cancel is
   *  needed, Gate-B F1). */
  cancelBusy: boolean;
}

export function BuildProgress({
  phase,
  result,
  briefId,
  error,
  onRetry,
  onCancel,
  onTerminalFailure,
  busy,
  cancelBusy,
}: BuildProgressProps) {
  const t = useT();

  // While building, the synchronous build endpoint hasn't returned a course id
  // yet — poll the brief→course shell (committed BEFORE the pipeline, Gate-B F1)
  // to obtain the cancel target + detect a terminal flip. A 404 (shell not
  // materialized yet) is expected early; keep polling.
  const briefCourseQ = useQuery({
    queryKey: qk.briefCourse(briefId ?? "none"),
    queryFn: () => Define.briefCourse(briefId as string),
    enabled: !!briefId && phase === "building" && !result,
    refetchInterval: phase === "building" ? 1500 : false,
    retry: false, // a 404 is the "still spinning up" signal, not an error to retry
  });

  // The effective course id: the build result once it lands, else the polled
  // in-flight shell id.
  const courseId = result?.course_id ?? briefCourseQ.data?.course_id ?? null;

  // A server-side flip to build_failed while building (e.g. cancel) surfaces via
  // the poll → drive the page to its failed terminal state (ADR-0026 / R-S10).
  const polledStatus = briefCourseQ.data?.status;
  useEffect(() => {
    if (phase === "building" && polledStatus === "build_failed") {
      onTerminalFailure(t("define.error.cancelled"));
    }
  }, [phase, polledStatus, onTerminalFailure, t]);

  // Poll the trace while building so the timeline fills in; once we have a
  // result the build already landed, so a single fetch is enough — but we keep
  // a short refetch so a still-committing trace row appears.
  const traceQ = useQuery({
    queryKey: ["draft-trace", courseId],
    queryFn: () => AI.draftTrace(courseId as string),
    enabled: !!courseId,
    refetchInterval: phase === "building" ? 1500 : false,
  });

  // Poll the course status during the build so a server-side flip to
  // build_failed (e.g. via cancel) surfaces here too (ADR-0026 / R-S10).
  useQuery({
    queryKey: qk.course(courseId ?? "none"),
    queryFn: () => Courses.get(courseId as string),
    enabled: !!courseId && phase === "building",
    refetchInterval: 1500,
  });

  return (
    <section
      data-testid="build-progress"
      aria-labelledby="build-progress-heading"
      className="flex flex-col gap-6"
    >
      <header className="flex flex-col gap-2">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {t("define.build.cartouche")}
        </p>
        <h2
          id="build-progress-heading"
          className="font-display text-2xl leading-tight tracking-tight"
        >
          {phase === "success"
            ? t("define.build.doneTitle")
            : phase === "failed"
              ? t("define.build.failedTitle")
              : t("define.build.title")}
        </h2>
      </header>

      {phase === "building" && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 font-body text-sm text-muted-foreground"
        >
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {t("define.build.working")}
        </div>
      )}

      {phase === "failed" ? (
        <div
          data-testid="build-failed"
          className="surface flex flex-col items-start gap-3 border-destructive/40 p-5"
        >
          <p className="flex items-center gap-2 font-display text-base leading-tight text-foreground">
            <AlertTriangle className="h-5 w-5 text-destructive" aria-hidden />
            {t("define.build.failedHeading")}
          </p>
          <p className="font-body text-sm text-muted-foreground">
            {error || t("define.build.failedBody")}
          </p>
          <Button type="button" onClick={onRetry} disabled={busy}>
            <RotateCcw className="me-2 h-4 w-4" aria-hidden />
            {t("define.build.retry")}
          </Button>
        </div>
      ) : (
        <>
          {/* Reused CourseDraftTrace timeline (FR-DEFINE-17). */}
          {traceQ.data && traceQ.data.steps.length > 0 ? (
            <div className="flex flex-col gap-3">
              <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {t("define.build.timeline")}
              </p>
              <DraftTraceTimeline steps={traceQ.data.steps} />
            </div>
          ) : phase === "building" ? (
            <p className="font-body text-sm text-muted-foreground">
              {t("define.build.timelinePending")}
            </p>
          ) : null}

          {phase === "success" && result && (
            <div className="surface flex flex-col items-start gap-3 border-primary/40 p-5">
              <p className="font-body text-sm text-foreground">
                {t("define.build.doneBody", {
                  modules: result.module_count,
                  lessons: result.lesson_count,
                })}
              </p>
              <Link href={`/learn/${result.slug}`}>
                <Button type="button">
                  {t("define.build.startLearning")}
                  <ArrowRight className="ms-2 h-4 w-4" aria-hidden />
                </Button>
              </Link>
            </div>
          )}

          {phase === "building" && courseId && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => onCancel(courseId)}
              disabled={cancelBusy}
              className="self-start text-muted-foreground"
            >
              <X className="me-2 h-4 w-4" aria-hidden />
              {t("define.build.cancel")}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
