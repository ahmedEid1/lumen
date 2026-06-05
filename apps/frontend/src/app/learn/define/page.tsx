"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Define } from "@/lib/api/endpoints";
import { useAuth } from "@/lib/auth/store";
import { useT } from "@/lib/i18n/provider";
import { GoalIntakeChat, type ChatTurn } from "@/components/define/GoalIntakeChat";
import { BriefReview } from "@/components/define/BriefReview";
import { BuildProgress } from "@/components/define/BuildProgress";
import type { MessageKey } from "@/lib/i18n/messages/en";
import type {
  BriefDraft,
  DraftFromBriefResponse,
  GoalTurnResponse,
} from "@/lib/api/types";

type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

/**
 * /learn/define — the define → build → learn journey (S3.11).
 *
 * The canonical, learner-facing self-serve build entry (FR-DEFINE-09): a learner
 * describes a fuzzy goal, runs a bounded multi-turn clarification (R-M10), reviews
 * the accumulated brief, explicitly confirms (FR-DEFINE-07 — a build NEVER starts
 * automatically), watches the build progress via the reused CourseDraftTrace
 * timeline (FR-DEFINE-17), and is deep-linked into their PRIVATE course's learn
 * surface when the build lands (FR-LEARN-01).
 *
 * This is NOT `/studio` — authoring-for-others lives there; this is
 * authoring-to-learn. The state machine is a simple linear phase walk with a
 * back-edge from review to the conversation (un-finalized brief is mutable,
 * FR-DEFINE-08). The raw goal never leaves the input box: the server encrypts it
 * at rest and only ever returns the structured paraphrase (FR-PRIV-01).
 */

type Phase = "intake" | "review" | "building" | "done" | "failed";

function normalizeError(err: unknown, t: Translate): string {
  if (err && typeof err === "object" && "code" in err) {
    const code = String((err as { code?: unknown }).code ?? "");
    const known: Record<string, MessageKey> = {
      "define.turn_cap": "define.error.turnCap",
      "define.build_in_flight": "define.error.buildInFlight",
      "define.build_quota": "define.error.buildQuota",
      "define.build_failed": "define.error.buildFailed",
      "define.brief_finalized": "define.error.briefFinalized",
      "define.session_not_found": "define.error.sessionNotFound",
    };
    if (code in known) return t(known[code]);
  }
  if (err instanceof Error && err.message) return err.message;
  return t("define.error.generic");
}

export default function DefinePage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const t = useT();

  const [phase, setPhase] = useState<Phase>("intake");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [latest, setLatest] = useState<GoalTurnResponse | null>(null);
  const [buildResult, setBuildResult] = useState<DraftFromBriefResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The brief id, captured the first time we finalize, so a retry re-runs the
  // SAME (idempotent) build rather than minting a new draft. Mirrored into state
  // (`buildBriefId`) so BuildProgress's brief→course poll activates reactively
  // (a ref change wouldn't re-render the poll's `enabled` gate).
  const finalizedBriefId = useRef<string | null>(null);
  const [buildBriefId, setBuildBriefId] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/learn/define");
  }, [ready, user, router]);

  const startM = useMutation({
    mutationFn: (goal: string) => Define.startGoal(goal),
    onMutate: (goal: string) => {
      setError(null);
      setTurns((prev) => [...prev, { role: "user", text: goal }]);
    },
    onSuccess: (res) => {
      setLatest(res);
      setTurns((prev) => [...prev, { role: "assistant", text: res.assistant_message }]);
    },
    onError: (err) => setError(normalizeError(err, t)),
  });

  const turnM = useMutation({
    mutationFn: (message: string) => {
      if (!latest) throw new Error("no session");
      return Define.takeTurn(latest.session_id, message);
    },
    onMutate: (message: string) => {
      setError(null);
      setTurns((prev) => [...prev, { role: "user", text: message }]);
    },
    onSuccess: (res) => {
      setLatest(res);
      setTurns((prev) => [...prev, { role: "assistant", text: res.assistant_message }]);
    },
    onError: (err) => setError(normalizeError(err, t)),
  });

  // Finalize → build, in sequence, on the single explicit confirm. We finalize
  // once (capturing the brief id) so a retry replays the same idempotent build.
  const buildM = useMutation({
    mutationFn: async (edits: BriefDraft) => {
      let briefId = finalizedBriefId.current;
      if (!briefId) {
        if (!latest) throw new Error("no session");
        const finalized = await Define.finalize(latest.session_id, edits);
        briefId = finalized.id;
        finalizedBriefId.current = briefId;
        setBuildBriefId(briefId); // activate the brief→course poll (Gate-B F1)
      }
      return Define.draftFromBrief(briefId);
    },
    onMutate: () => {
      setError(null);
      setPhase("building");
    },
    onSuccess: (res) => {
      setBuildResult(res);
      setPhase("done");
    },
    onError: (err) => {
      setError(normalizeError(err, t));
      setPhase("failed");
    },
  });

  const cancelM = useMutation({
    // The course id comes from BuildProgress: while building it is the polled
    // shell id (Gate-B F1), once landed it is the build result's id.
    mutationFn: (courseId: string) => Define.cancelBuild(courseId),
    onSuccess: () => {
      setError(t("define.error.cancelled"));
      setPhase("failed");
    },
    onError: (err) => setError(normalizeError(err, t)),
  });

  if (!ready || !user) return null;

  const buildPhase =
    phase === "done" ? "success" : phase === "failed" ? "failed" : "building";

  return (
    <div className="container mx-auto flex max-w-3xl flex-col gap-8 px-6 py-14">
      <header className="flex flex-col gap-3">
        <p className="flex items-center gap-1.5 font-mono text-xs uppercase tracking-wider text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
          {t("define.cartouche")}
        </p>
        <h1 className="font-display text-3xl leading-tight tracking-tight sm:text-4xl">
          {t("define.title")}
        </h1>
        <p className="font-body text-sm text-muted-foreground">{t("define.subtitle")}</p>
      </header>

      {phase === "intake" && (
        <GoalIntakeChat
          turns={turns}
          latest={latest}
          pending={startM.isPending || turnM.isPending}
          error={error}
          onStart={(goal) => startM.mutate(goal)}
          onReply={(message) => turnM.mutate(message)}
          onReview={() => setPhase("review")}
        />
      )}

      {phase === "review" && latest && (
        <BriefReview
          brief={latest.accumulated_brief}
          pending={buildM.isPending}
          onConfirm={(edits) => buildM.mutate(edits)}
          onBack={() => setPhase("intake")}
        />
      )}

      {(phase === "building" || phase === "done" || phase === "failed") && (
        <BuildProgress
          phase={buildPhase}
          result={buildResult}
          briefId={buildBriefId}
          error={error}
          busy={buildM.isPending || cancelM.isPending}
          // The cancel button must stay enabled WHILE the build is pending — that
          // is the whole window it is for — so it is gated only by an in-flight
          // cancel, never by buildM.isPending (Gate-B F1).
          cancelBusy={cancelM.isPending}
          onRetry={() => buildM.mutate({})}
          onCancel={(courseId) => cancelM.mutate(courseId)}
          onTerminalFailure={(msg) => {
            setError(msg);
            setPhase("failed");
          }}
        />
      )}
    </div>
  );
}
