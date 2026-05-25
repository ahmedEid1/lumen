"use client";

/**
 * Personalized learning-path dashboard — Workbench surface.
 *
 * Lumen v2 Phase I5. Three pieces stack vertically:
 *
 * 1. The "what to do today" widget — single action card driven by
 *    the agent's ``next_action`` hint plus the learner's current
 *    FSRS due-count. If the learner has overdue cards, the widget
 *    redirects them to the review queue first; otherwise it deep-
 *    links to the next lesson on the active path.
 * 2. The path itself — a ``MilestoneTable`` grouped by milestone,
 *    each row showing the course + status pill + "Open course"
 *    link. The first pending step gets the lime accent so the
 *    learner's eye lands on "do this next".
 * 3. A small disclosure that reveals the agent's rationale text
 *    (a paragraph of natural language the LLM emitted explaining
 *    its choices) — the "show me how the agent thinks" moat.
 *
 * Empty state: a goal-entry form (``PathBuilderForm``) that POSTs
 * to /api/v1/me/learning-path and redirects the user to refresh
 * once the new path is built. This is the single entry point —
 * subsequent re-plans happen automatically (monthly Celery beat)
 * or via the explicit "Replan" button on the populated state.
 *
 * Workbench rules applied:
 * - Single lime accent: the first pending step's row + the
 *   "Build my path" / "Replan" CTAs.
 * - Mono for IDs, weeks, milestone labels; display for the page
 *   heading + course titles; body for prose.
 * - Borders do the elevation work; no shadows on cards.
 *
 * The whole page lives behind the standard /dashboard layout
 * guard — unauthenticated visitors are redirected to /login.
 *
 * i18n note: the page uses inline English strings rather than the
 * ``t()`` typed-key system because the spec marks the messages
 * file as off-limits for this commit. The orchestrator (or a
 * follow-up i18n pass) will extract them once the surface stabilises.
 *
 * TODO(orchestrator): add a sidebar nav entry pointing at
 * /dashboard/path. The current /dashboard layout doesn't have a
 * shared sidebar component yet; if one lands as part of Phase I4
 * (agent-trace observability), wire the link in there.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/store";
import { MilestoneTable } from "./components/MilestoneTable";
import { PathBuilderForm } from "./components/PathBuilderForm";
import { TodayWidget } from "./components/TodayWidget";
import {
  pathKeys,
  type LearningPathOut,
} from "./components/types";

export default function LearningPathPage() {
  const { user, ready, token } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/dashboard/path");
  }, [ready, user, router]);

  // ``404`` from the server means "no active path" — TanStack
  // surfaces it as an error; we treat the error as the empty
  // state rather than rendering an error banner.
  const pathQ = useQuery<LearningPathOut | null>({
    queryKey: pathKeys.active,
    queryFn: async () => {
      try {
        return await api<LearningPathOut>("/api/v1/me/learning-path", {
          token: token ?? undefined,
        });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    enabled: !!user,
    retry: false,
  });

  const replanMut = useMutation<LearningPathOut, ApiError>({
    mutationFn: () =>
      api<LearningPathOut>("/api/v1/me/learning-path/replan", {
        method: "POST",
        token: token ?? undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: pathKeys.active });
      qc.invalidateQueries({ queryKey: pathKeys.today });
    },
  });

  if (!ready || !user) return null;

  const path = pathQ.data ?? null;
  const isLoading = pathQ.isLoading;

  return (
    <div className="container mx-auto px-6 py-14 sm:py-20">
      <header className="mb-12 flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Learning path
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          Your personalized path
        </h1>
        <p className="font-body text-sm text-muted-foreground">
          An eight-course curriculum built from your goal, re-planned
          monthly as you make progress.
        </p>
      </header>

      {isLoading ? (
        <div className="surface h-32 animate-pulse" aria-hidden />
      ) : path === null ? (
        <PathBuilderForm
          token={token ?? undefined}
          onCreated={() => {
            qc.invalidateQueries({ queryKey: pathKeys.active });
            qc.invalidateQueries({ queryKey: pathKeys.today });
          }}
        />
      ) : (
        <PopulatedView
          path={path}
          token={token ?? undefined}
          onReplan={() => replanMut.mutate()}
          replanning={replanMut.isPending}
        />
      )}
    </div>
  );
}

function PopulatedView({
  path,
  token,
  onReplan,
  replanning,
}: {
  path: LearningPathOut;
  token: string | undefined;
  onReplan: () => void;
  replanning: boolean;
}) {
  const [showRationale, setShowRationale] = useState(false);

  // Find the first pending step so we can lime-accent it as
  // "do this next" in the table. If everything is completed we
  // pass null so nothing gets the highlight.
  const nextStepId =
    path.steps.find((s) => s.status === "pending")?.id ?? null;

  return (
    <div className="flex flex-col gap-10">
      <TodayWidget token={token} />

      <section>
        <div className="mb-5 flex items-baseline justify-between gap-3">
          <h2 className="font-display text-lg leading-tight tracking-tight">
            Milestones
          </h2>
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {path.steps.length} courses
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={replanning}
              onClick={onReplan}
            >
              {replanning ? "Replanning…" : "Replan"}
            </Button>
          </div>
        </div>

        <MilestoneTable
          steps={path.steps}
          highlightStepId={nextStepId}
          token={token}
        />
      </section>

      <section>
        <button
          type="button"
          onClick={() => setShowRationale((v) => !v)}
          className="font-mono text-xs uppercase tracking-wider text-muted-foreground transition-colors duration-[160ms] hover:text-foreground"
          aria-expanded={showRationale}
        >
          {showRationale ? "Hide agent rationale" : "Why this plan?"}
        </button>
        {showRationale && (
          <div className="surface mt-3 p-5">
            <p className="whitespace-pre-line font-body text-sm leading-relaxed text-foreground/90">
              {path.rationale ||
                "The agent did not include a rationale for this plan."}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
