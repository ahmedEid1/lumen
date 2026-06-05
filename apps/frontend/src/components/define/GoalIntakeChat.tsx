"use client";

import { useEffect, useRef, useState } from "react";
import { Sparkles, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n/provider";
import { cn } from "@/lib/utils";
import type { BriefDraft, GoalTurnResponse } from "@/lib/api/types";

/**
 * GoalIntakeChat (S3.11 / FR-DEFINE-01/02/09).
 *
 * The learner-facing, chat-like bounded clarification surface that drives the
 * `/ai/goal/*` elicitation. It is deliberately NOT a free-form chat: the
 * conversation is bounded (6 turns server-side, R-M10), and every assistant
 * reply ships an *accumulated brief* that the learner watches fill in turn by
 * turn (FR-DEFINE-08). When the server reports convergence OR the turn cap is
 * reached the input is replaced by a "review your brief" affordance — a build
 * never starts from here (FR-DEFINE-07).
 *
 * a11y (FR-A11Y-01): the transcript is an `aria-live="polite"` log so each new
 * assistant turn is announced; inputs are explicitly labelled; the turn-cap
 * notice has `role="status"`.
 */

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

interface GoalIntakeChatProps {
  /** Conversation transcript, oldest first. */
  turns: ChatTurn[];
  /** The latest server turn, or null before the session starts. */
  latest: GoalTurnResponse | null;
  /** True while a start/turn request is in flight. */
  pending: boolean;
  /** A normalized error message to surface inline, or null. */
  error: string | null;
  /** Open the goal-intake with a fuzzy goal. */
  onStart: (goal: string) => void;
  /** Advance the conversation by one reply. */
  onReply: (message: string) => void;
  /** Move to the brief-review step (convergence/cap reached). */
  onReview: () => void;
}

export function GoalIntakeChat({
  turns,
  latest,
  pending,
  error,
  onStart,
  onReply,
  onReview,
}: GoalIntakeChatProps) {
  const t = useT();
  const [goal, setGoal] = useState("");
  const [reply, setReply] = useState("");
  const logRef = useRef<HTMLDivElement | null>(null);

  // Keep the newest turn in view as the transcript grows.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [turns.length]);

  const started = latest !== null;
  const capReached = latest ? latest.turns_remaining <= 0 : false;
  const converged = latest ? latest.converged : false;
  // The conversation is "done" — no more replies accepted — when the server
  // says we converged OR the bounded turn budget is spent (R-M10).
  const conversationDone = started && (converged || capReached);

  function submitStart(e: React.FormEvent) {
    e.preventDefault();
    const g = goal.trim();
    if (!g || pending) return;
    onStart(g);
  }

  function submitReply(e: React.FormEvent) {
    e.preventDefault();
    const m = reply.trim();
    if (!m || pending) return;
    onReply(m);
    setReply("");
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Transcript — an aria-live log so each new turn is announced. */}
      <div
        ref={logRef}
        data-testid="goal-chat-log"
        aria-live="polite"
        aria-label={t("define.chat.logLabel")}
        className="flex max-h-[28rem] flex-col gap-3 overflow-y-auto"
      >
        {!started && (
          <p className="font-body text-sm text-muted-foreground">
            {t("define.chat.intro")}
          </p>
        )}
        {turns.map((turn, i) => (
          <div
            key={i}
            data-role={turn.role}
            className={cn(
              "max-w-[42rem] rounded-md border px-4 py-3 font-body text-sm leading-relaxed",
              turn.role === "assistant"
                ? "border-border bg-card/40 text-foreground"
                : "ms-auto border-primary/30 bg-primary/5 text-foreground",
            )}
          >
            {turn.role === "assistant" && (
              <span className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                <Sparkles className="h-3 w-3" aria-hidden />
                {t("define.chat.assistantLabel")}
              </span>
            )}
            {turn.text}
          </div>
        ))}
        {pending && (
          <p
            role="status"
            className="font-mono text-xs text-muted-foreground"
            data-testid="goal-chat-pending"
          >
            {t("define.chat.thinking")}
          </p>
        )}
      </div>

      {error && (
        <p
          role="alert"
          data-testid="goal-chat-error"
          className="font-body text-sm text-destructive"
        >
          {error}
        </p>
      )}

      {/* Composer — start, then reply, then review when bounded/converged. */}
      {!started ? (
        <form onSubmit={submitStart} className="flex flex-col gap-3">
          <label
            htmlFor="define-goal"
            className="font-body text-sm font-medium text-foreground"
          >
            {t("define.chat.goalLabel")}
          </label>
          <textarea
            id="define-goal"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            rows={3}
            maxLength={4000}
            placeholder={t("define.chat.goalPlaceholder")}
            className="w-full resize-y rounded-md border border-border bg-card/40 px-3 py-2 font-body text-sm text-foreground outline-none transition-colors duration-[160ms] focus-visible:border-foreground/40"
          />
          <Button type="submit" disabled={!goal.trim() || pending} className="self-start">
            {t("define.chat.start")} <ArrowRight className="ms-2 h-4 w-4" aria-hidden />
          </Button>
        </form>
      ) : conversationDone ? (
        <div className="flex flex-col gap-3">
          {capReached && (
            <p
              role="status"
              data-testid="turn-cap-notice"
              className="surface px-4 py-3 font-body text-sm text-muted-foreground"
            >
              {t("define.chat.turnCap")}
            </p>
          )}
          <Button onClick={onReview} className="self-start">
            {t("define.chat.review")} <ArrowRight className="ms-2 h-4 w-4" aria-hidden />
          </Button>
        </div>
      ) : (
        <form onSubmit={submitReply} className="flex flex-col gap-3">
          <label
            htmlFor="define-reply"
            className="font-body text-sm font-medium text-foreground"
          >
            {t("define.chat.replyLabel")}
          </label>
          <div className="flex items-end gap-2">
            <textarea
              id="define-reply"
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              rows={2}
              maxLength={4000}
              placeholder={t("define.chat.replyPlaceholder")}
              className="w-full resize-y rounded-md border border-border bg-card/40 px-3 py-2 font-body text-sm text-foreground outline-none transition-colors duration-[160ms] focus-visible:border-foreground/40"
            />
            <Button type="submit" disabled={!reply.trim() || pending}>
              {t("define.chat.send")}
            </Button>
          </div>
          {latest && (
            <p className="font-mono text-xs tabular-nums text-muted-foreground">
              {t("define.chat.turnsRemaining", { n: latest.turns_remaining })}
            </p>
          )}
        </form>
      )}

      {/* Live running-brief preview so the learner sees it accumulate. */}
      {latest && <RunningBrief brief={latest.accumulated_brief} />}
    </div>
  );
}

function RunningBrief({ brief }: { brief: BriefDraft }) {
  const t = useT();
  const outcomes = brief.desired_outcomes ?? [];
  const hasAny =
    brief.goal_summary ||
    brief.level ||
    brief.time_budget_hours ||
    brief.sessions_per_week ||
    outcomes.length > 0;
  if (!hasAny) return null;
  return (
    <section
      data-testid="running-brief"
      aria-label={t("define.brief.runningLabel")}
      className="surface flex flex-col gap-2 p-4"
    >
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {t("define.brief.runningLabel")}
      </p>
      {brief.goal_summary && (
        <p className="font-body text-sm text-foreground">{brief.goal_summary}</p>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs tabular-nums text-muted-foreground">
        {brief.level && (
          <BriefRow label={t("define.brief.level")} value={brief.level} />
        )}
        {brief.time_budget_hours != null && (
          <BriefRow
            label={t("define.brief.timeBudget")}
            value={t("define.brief.hours", { n: brief.time_budget_hours })}
          />
        )}
        {brief.sessions_per_week != null && (
          <BriefRow
            label={t("define.brief.sessions")}
            value={String(brief.sessions_per_week)}
          />
        )}
      </dl>
      {outcomes.length > 0 && (
        <ul className="list-disc ps-4 font-body text-sm text-foreground/80">
          {outcomes.map((o, i) => (
            <li key={i}>{o}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BriefRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="text-foreground/80">{value}</dd>
    </div>
  );
}
