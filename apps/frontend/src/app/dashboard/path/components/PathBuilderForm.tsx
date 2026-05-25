"use client";

/**
 * Goal-entry form — the path's empty state.
 *
 * Submits the learner's stated goal to ``POST /api/v1/me/learning-path``
 * and, on success, invalidates the parent page's query so the
 * Populated view takes over. We keep this client-side because the
 * goal is a textarea + validation + an LLM-bound request that can
 * take 5-15s; a server-action submit would block the page
 * transition for the full duration. The button surfaces a
 * "Building…" spinner instead.
 *
 * The submit path can return:
 * - 201 with the built path → success
 * - 422 if the goal is empty / too short → highlight the field
 * - 429 if rate-limited or the user is over their LLM budget
 * - 502 if the LLM emitted two malformed plans in a row →
 *   show a try-again message
 *
 * Each failure mode reads ``ApiError.code`` and renders a
 * matching English string (i18n extraction is a follow-up).
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api/client";
import type { LearningPathOut } from "./types";

const PLACEHOLDER =
  "I want to be a backend engineer in 6 months. I know basic Python and " +
  "some SQL but I've never built a production API.";

export function PathBuilderForm({
  token,
  onCreated,
}: {
  token: string | undefined;
  onCreated: (path: LearningPathOut) => void;
}) {
  const [goal, setGoal] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const mut = useMutation<LearningPathOut, ApiError, { goal: string }>({
    mutationFn: ({ goal }) =>
      api<LearningPathOut>("/api/v1/me/learning-path", {
        method: "POST",
        body: { goal },
        token,
      }),
    onSuccess: (data) => {
      setErrorMessage(null);
      onCreated(data);
    },
    onError: (err) => {
      // Map ``ApiError.code`` to a friendly message; fall back to
      // the raw message for codes we haven't translated yet.
      if (err.code === "learning_path.empty_catalog") {
        setErrorMessage(
          "The catalog doesn't have any published courses yet. " +
            "Ask an instructor to publish something first.",
        );
      } else if (err.code === "learning_path.llm_invalid_output") {
        setErrorMessage(
          "The AI returned an unexpected response. Please try again in a minute.",
        );
      } else if (err.code === "llm.budget_exceeded") {
        setErrorMessage(
          "You've reached today's AI usage limit. Try again tomorrow.",
        );
      } else if (err.status === 429) {
        setErrorMessage(
          "Too many requests right now. Please wait a moment and try again.",
        );
      } else {
        setErrorMessage(err.message || "Could not build a path.");
      }
    },
  });

  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = goal.trim();
    if (trimmed.length < 4) {
      setErrorMessage(
        "Tell us a bit more about your goal — at least a sentence.",
      );
      return;
    }
    setErrorMessage(null);
    mut.mutate({ goal: trimmed });
  };

  const submitting = mut.isPending;

  return (
    <section className="surface p-6 sm:p-8">
      <h2 className="font-display text-lg leading-tight tracking-tight">
        Tell the agent what you want to learn
      </h2>
      <p className="mt-2 font-body text-sm text-muted-foreground">
        State your goal in plain English. The agent will pick courses,
        sequence them by prerequisite, and pace them around your
        spaced-repetition queue.
      </p>

      <form onSubmit={onSubmit} className="mt-5 flex flex-col gap-3">
        <label htmlFor="path-goal" className="sr-only">
          Goal
        </label>
        <Textarea
          id="path-goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={4}
          maxLength={2000}
          disabled={submitting}
          aria-invalid={errorMessage ? "true" : "false"}
        />
        {errorMessage && (
          <p
            role="alert"
            className="font-body text-sm text-destructive"
          >
            {errorMessage}
          </p>
        )}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {submitting
              ? "Building your path — this may take 10-15 seconds."
              : "Plans are re-built automatically once a month."}
          </p>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Building…" : "Build my path"}
          </Button>
        </div>
      </form>
    </section>
  );
}
