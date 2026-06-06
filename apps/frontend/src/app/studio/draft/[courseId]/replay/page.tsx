"use client";

import { use, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Courses, Traces } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import { CostBadge } from "@/components/trace/CostBadge";
import { TraceTimeline } from "@/components/trace/TraceTimeline";
import type { TraceStep } from "@/lib/api/endpoints";

/**
 * Instructor-facing course-draft replay (Lumen v2 Phase I4).
 *
 * Same data as the studio timeline at /studio/draft/[courseId]
 * but presented as a play-by-play with auto-advance + scrub bar.
 * The instructor lands here to watch the agent thinking unfold
 * one step at a time — useful when a draft scored low and you
 * want to pinpoint *which* step went off the rails.
 *
 * Three end-of-replay actions:
 *   - Accept (publish-anyway)
 *   - Revise this myself (jump to /studio/{courseId})
 *   - Restart (reset to step 0)
 *
 * Auth: the API endpoint enforces owner-or-admin. The page-level
 * redirect just keeps the URL out of the wrong hands on the
 * client.
 */
export default function DraftReplayPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = use(params);
  const { user, ready } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();

  useEffect(() => {
    if (!ready) return;
    // S1.11: the draft replay is open to any authenticated user.
    if (!user) {
      router.replace(`/login?next=/studio/draft/${courseId}/replay`);
    }
  }, [ready, user, router, courseId]);

  const replayQ = useQuery({
    queryKey: ["draft-replay", courseId],
    queryFn: () => Traces.draftReplay(courseId),
    enabled: !!user,
  });
  const courseQ = useQuery({
    queryKey: qk.course(courseId),
    queryFn: () => Courses.get(courseId),
    enabled: !!user,
  });

  const publish = useMutation({
    mutationFn: () => Courses.patch(courseId, { status: "published" }),
    onSuccess: async () => {
      toast.success("Course published.");
      await qc.invalidateQueries({ queryKey: qk.course(courseId) });
      router.push(`/studio/${courseId}`);
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Publish failed.");
    },
  });

  if (!ready || !user) return null;

  if (replayQ.isLoading || courseQ.isLoading) {
    return (
      <div className="container mx-auto px-6 py-14">
        <p className="font-mono text-xs text-muted-foreground">
          Loading replay...
        </p>
      </div>
    );
  }

  if (replayQ.isError || !replayQ.data) {
    return (
      <div className="container mx-auto px-6 py-14">
        <div className="surface flex flex-col items-start gap-3 p-6">
          <p className="font-display text-base leading-tight">
            Could not load the replay.
          </p>
          <p className="font-body text-sm text-muted-foreground">
            {replayQ.error instanceof Error
              ? replayQ.error.message
              : "Unknown error."}
          </p>
          <Link href="/studio">
            <Button variant="outline" size="sm">
              <ArrowLeft className="me-2 h-4 w-4" /> Back to studio
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  const data = replayQ.data;
  // Adapt DraftReplayStep to TraceStep shape — the timeline
  // expects the unified TraceStep envelope. Map ``id`` → ``trace_id``;
  // the draft steps don't carry parent_trace_id / parent_call_id
  // pointers (I3's table doesn't surface them on the API), so we
  // null them out — TraceTimeline doesn't currently render the
  // parent links visually.
  const steps: TraceStep[] = data.steps.map((s) => ({
    trace_id: s.id,
    parent_trace_id: null,
    parent_call_id: null,
    step: s.step,
    step_index: s.step_index,
    payload: s.payload,
    duration_ms: s.duration_ms,
    status: s.status,
    created_at: s.created_at,
  }));

  return (
    <div className="container mx-auto flex max-w-5xl flex-col gap-8 px-6 py-14">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Link href={`/studio/draft/${courseId}`}>
            <Button variant="ghost" size="sm">
              <ArrowLeft className="me-2 h-4 w-4" /> Back to trace
            </Button>
          </Link>
        </div>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          AI authoring replay
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {courseQ.data?.title ?? "Drafted course"}
        </h1>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">
          draft_id {data.draft_id ?? "(none)"} · {data.step_count} step
          {data.step_count === 1 ? "" : "s"}
        </p>
      </header>

      <CostBadge
        costUsd="0"
        latencyMs={data.total_duration_ms}
        totalTokens={0}
        stepCount={data.step_count}
        label="Replay totals"
      />

      <section className="flex flex-col gap-3">
        <h2 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Play-by-play
        </h2>
        <TraceTimeline
          steps={steps}
          autoPlay
          stepDurationMs={1500}
          emptyLabel="No trace recorded for this draft."
        />
      </section>

      <section
        className="flex flex-col items-start gap-3 sm:flex-row sm:items-center"
        data-testid="replay-end-actions"
      >
        <Button
          type="button"
          variant="default"
          onClick={() => publish.mutate()}
          disabled={publish.isPending}
          data-testid="replay-accept"
        >
          Accept &amp; publish
        </Button>
        <Link href={`/studio/${courseId}`}>
          <Button variant="outline" data-testid="replay-revise">
            Revise this myself
          </Button>
        </Link>
        <Link href={`/studio/draft/${courseId}/replay`}>
          <Button
            variant="ghost"
            data-testid="replay-restart-link"
            onClick={() => replayQ.refetch()}
          >
            Restart replay
          </Button>
        </Link>
      </section>
    </div>
  );
}
