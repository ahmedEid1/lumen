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
    if (!user) router.replace(`/login?next=/studio/draft/${courseId}`);
    else if (user.role === "student") router.replace("/dashboard");
  }, [ready, user, router, courseId]);

  const traceQ = useQuery({
    queryKey: ["draft-trace", courseId],
    queryFn: () => AI.draftTrace(courseId),
    enabled: !!user && user.role !== "student",
  });
  const courseQ = useQuery({
    queryKey: qk.course(courseId),
    queryFn: () => Courses.get(courseId),
    enabled: !!user && user.role !== "student",
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

  if (!ready || !user || user.role === "student") return null;

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
            <PublishAnywayButton
              onClick={() => publish.mutate()}
              disabled={publish.isPending}
            />
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
