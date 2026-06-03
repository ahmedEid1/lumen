"use client";

import { use, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AI, Courses } from "@/lib/api/endpoints";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/lib/auth/store";
import {
  DraftTraceTimeline,
  FinalScoreBadge,
  PublishAnywayButton,
  type FinalScore,
} from "./components/draft-trace-timeline";

/**
 * Studio draft trace viewer (Lumen v2 Phase I3).
 *
 * The instructor lands here after the AI orchestrator runs
 * researcher → outliner → critic ↺ reviser → lesson-drafter →
 * final-critic. The page renders the full critique-revise chain
 * top-to-bottom plus the final critic's score at the top so the
 * instructor can decide whether to publish or revise.
 *
 * The page is a client component (mirrors the existing studio surfaces)
 * but uses TanStack Query so the data fetch is cache-aware and
 * authenticated-by-cookie automatically.
 *
 * Auth guard: redirects to /login on missing user; redirects to the
 * student dashboard for non-instructor roles. The API enforces the
 * owner-only gate; this just keeps the URL out of the wrong hands.
 */

export default function DraftTracePage({
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
    // S1.11: the draft studio is open to any authenticated user.
    if (!user) router.replace(`/login?next=/studio/draft/${courseId}`);
  }, [ready, user, router, courseId]);

  const traceQ = useQuery({
    queryKey: ["draft-trace", courseId],
    queryFn: () => AI.draftTrace(courseId),
    enabled: !!user,
  });
  const courseQ = useQuery({
    queryKey: qk.course(courseId),
    queryFn: () => Courses.get(courseId),
    enabled: !!user,
  });

  // Two-control model (S2.11 / ADR-0026): the lifecycle control publishes
  // (draft↔published, course stays PRIVATE), and a separate Share control
  // (enabled only once published) flips public/private. Publishing alone no
  // longer lists the course; sharing routes it through moderation.
  const invalidateCourseViews = async () => {
    await qc.invalidateQueries({ queryKey: qk.course(courseId) });
    // Prefix-invalidate every catalog/subjects/tags query at once.
    await qc.invalidateQueries({ queryKey: qk.catalogRoot });
    await qc.invalidateQueries({ queryKey: qk.myCourses });
    await qc.invalidateQueries({ queryKey: qk.moderationQueue });
  };

  const publish = useMutation({
    mutationFn: () => Courses.publish(courseId),
    onSuccess: async () => {
      toast.success("Course published (private). Use Share to list it publicly.");
      await invalidateCourseViews();
      router.push(`/studio/${courseId}`);
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Publish failed.");
    },
  });

  const isPublished = courseQ.data?.status === "published";
  const isPublic = courseQ.data?.visibility === "public";
  const moderationState = courseQ.data?.moderation_state ?? null;

  const share = useMutation({
    mutationFn: () => (isPublic ? Courses.unshare(courseId) : Courses.share(courseId)),
    onSuccess: async () => {
      toast.success(isPublic ? "Course unshared (now private)." : "Submitted for review.");
      await invalidateCourseViews();
    },
    onError: (err: unknown) => {
      toast.error(err instanceof Error ? err.message : "Share toggle failed.");
    },
  });

  // S1 two-role: every authenticated user can author — no `student` gate.
  if (!ready || !user) return null;

  if (traceQ.isLoading || courseQ.isLoading) {
    return (
      <div className="container mx-auto px-6 py-14">
        <p className="font-body text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (traceQ.isError || !traceQ.data) {
    return (
      <div className="container mx-auto px-6 py-14">
        <div className="surface flex flex-col items-start gap-3 p-6">
          <p className="font-display text-base leading-tight">
            Could not load the draft trace.
          </p>
          <p className="font-body text-sm text-muted-foreground">
            {traceQ.error instanceof Error
              ? traceQ.error.message
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

  const data = traceQ.data;
  const finalStep = data.steps
    .filter((s) => s.step === "final_critic")
    .at(-1);
  const finalScore = extractFinalScore(finalStep?.payload);
  const revisionsUsed = data.steps.filter((s) => s.step === "reviser").length;

  return (
    <div className="container mx-auto flex max-w-5xl flex-col gap-8 px-6 py-14">
      <header className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Link href="/studio">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="me-2 h-4 w-4" /> Back to studio
            </Button>
          </Link>
        </div>
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          AI authoring reasoning trace
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {courseQ.data?.title ?? "Drafted course"}
        </h1>
        <p className="font-mono text-xs tabular-nums text-muted-foreground">
          draft_id {data.draft_id ?? "(none)"} ·{" "}
          {data.steps.length} step{data.steps.length === 1 ? "" : "s"} ·{" "}
          {revisionsUsed} revision{revisionsUsed === 1 ? "" : "s"}
        </p>
      </header>

      {finalScore && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          <div className="flex-1">
            <FinalScoreBadge score={finalScore} />
          </div>
          <div className="flex shrink-0 flex-col gap-2">
            {/* Lifecycle control — publish keeps the course PRIVATE. */}
            {!isPublished ? (
              <PublishAnywayButton
                onClick={() => publish.mutate()}
                disabled={publish.isPending}
              />
            ) : null}
            {/* Share control — enabled only once published (FR-VIS-23). */}
            <Button
              variant={isPublic ? "outline" : "default"}
              className="w-full"
              disabled={!isPublished || share.isPending}
              onClick={() => share.mutate()}
              title={
                !isPublished
                  ? "Publish the course before sharing it publicly"
                  : undefined
              }
            >
              {isPublic ? "Make private" : "Share publicly"}
            </Button>
            {isPublic && moderationState ? (
              <p
                className="font-mono text-xs text-muted-foreground"
                data-testid="moderation-state"
              >
                {moderationState === "pending_review"
                  ? "Pending review"
                  : moderationState === "approved"
                    ? "Approved · listed publicly"
                    : moderationState === "rejected"
                      ? "Rejected — revise and resubmit"
                      : moderationState === "delisted"
                        ? "Delisted by an admin"
                        : moderationState}
              </p>
            ) : null}
            <Link href={`/studio/${courseId}`}>
              <Button variant="outline" className="w-full">
                Edit before publishing
              </Button>
            </Link>
          </div>
        </div>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Step-by-step
        </h2>
        <DraftTraceTimeline steps={data.steps} />
      </section>
    </div>
  );
}

function extractFinalScore(
  payload: Record<string, unknown> | undefined,
): FinalScore | null {
  if (!payload) return null;
  const scores = payload.critic_scores as
    | { coverage?: unknown; learning_arc?: unknown; scope?: unknown }
    | undefined;
  if (
    !scores ||
    typeof scores.coverage !== "number" ||
    typeof scores.learning_arc !== "number" ||
    typeof scores.scope !== "number"
  ) {
    return null;
  }
  const mean = (scores.coverage + scores.learning_arc + scores.scope) / 3;
  const rationale =
    typeof payload.response_summary === "string"
      ? (payload.response_summary as string)
      : "";
  return {
    coverage: scores.coverage,
    learning_arc: scores.learning_arc,
    scope: scores.scope,
    mean,
    rationale,
  };
}
