"use client";

/**
 * L21b — Streaming tutor panel.
 *
 * Mounts when `flags.tutor_streaming === true` AND `supportsStreaming()`
 * returns true. Renders the same Workbench chrome as the legacy
 * `TutorPanel`, but the message flow is:
 *
 *   1. POST /api/v1/tutor/turns → returns turn_id (pending row).
 *   2. Open SSE to /api/v1/tutor/turns/{tid}/stream → render events
 *      as they arrive via `useTutorStream(turnId)`.
 *   3. On `turn_complete` / `turn_failed`, the panel unmounts the
 *      streaming surface and re-renders as a static history row.
 *
 * Today's L21a backend yields a noop event sequence — this UI is
 * what unlocks "watch it think" when the AsyncOpenAI streaming
 * follow-up + the L22 real LLM integration land.
 */

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/lib/i18n/provider";
import { useAuth } from "@/lib/auth/store";
import { renderTutorBody } from "@/lib/tutor/citations";
import { useTutorStream } from "@/lib/tutor/use-tutor-stream";
import { DemoQuestionChipRail } from "@/components/tutor/demo-question-chip-rail";
import {
  CostCapClosingCta,
  isCostCapError,
} from "@/components/tutor/cost-cap-closing-cta";

export interface StreamingTutorPanelProps {
  courseId: string;
  heading?: string;
  initialDraft?: string;
  /** Optional — used by the L22 chip rail to filter the library. */
  courseSlug?: string;
}

interface PostTurnResponse {
  id: string;
  status: string;
}

async function postTurn(
  content: string,
  courseSlug: string | null,
  token: string | null,
): Promise<PostTurnResponse> {
  const body: Record<string, string> = { content };
  if (courseSlug) body.course_slug = courseSlug;
  const res = await fetch("/api/v1/tutor/turns", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody?.error?.message ?? `POST /tutor/turns failed (${res.status})`);
  }
  return res.json() as Promise<PostTurnResponse>;
}

export function StreamingTutorPanel({
  courseId,
  heading,
  initialDraft,
  courseSlug,
}: StreamingTutorPanelProps) {
  const t = useT();
  const { token } = useAuth();
  const [draft, setDraft] = useState(initialDraft ?? "");
  const [currentTurnId, setCurrentTurnId] = useState<string | null>(null);
  const [sentPrompt, setSentPrompt] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const stream = useTutorStream(currentTurnId);

  const sendMut = useMutation({
    mutationFn: (content: string) => postTurn(content, courseSlug ?? null, token),
    onSuccess: (resp, content) => {
      setCurrentTurnId(resp.id);
      setSentPrompt(content);
      setDraft("");
    },
    onError: (err: Error) => {
      // Cost-cap errors render the closing CTA inline; suppress the
      // toast in that case so the user sees one focused surface.
      if (!isCostCapError(err)) {
        toast.error(err.message || t("tutor.sendError"));
      }
    },
  });

  // L23 — bubble POST-time cost-cap errors into the inline closing
  // CTA. The stream-time errors are already handled via the
  // `stream.phase === "failed"` branch below.
  const postTimeCostCap =
    sendMut.isError && isCostCapError(sendMut.error);

  const isInFlight =
    sendMut.isPending ||
    stream.phase === "planning" ||
    stream.phase === "tool" ||
    stream.phase === "synth";

  function handleSend(textOverride?: string) {
    const text = (textOverride ?? draft).trim();
    if (!text || isInFlight) return;
    sendMut.mutate(text);
  }

  // L32 — courseSlug now threads through to the backend which
  // resolves it to a course_id and runs pgvector retrieval against
  // that course's lessons. courseId stays in the prop signature for
  // parity with the legacy panel; it isn't sent on the wire because
  // the backend resolves the slug.
  void courseId;

  return (
    <div
      className="flex h-full flex-col surface"
      data-testid="streaming-tutor-panel"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          {heading ?? t("tutor.heading")}
        </p>
        <p className="font-mono text-[11px] uppercase tracking-wider text-primary">
          Streaming
        </p>
      </div>

      {!sentPrompt && (
        <DemoQuestionChipRail
          courseSlug={courseSlug}
          onPick={(prompt) => handleSend(prompt)}
        />
      )}

      <div
        ref={scrollRef}
        className="min-h-[280px] flex-1 space-y-4 overflow-y-auto p-4"
        data-testid="streaming-tutor-messages"
      >
        {postTimeCostCap && <CostCapClosingCta />}

        {!sentPrompt && !postTimeCostCap && (
          <div className="flex flex-col items-start gap-2 py-6 font-body text-sm text-muted-foreground">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            <p>{t("tutor.emptyPrompt")}</p>
          </div>
        )}

        {sentPrompt && (
          <div className="flex flex-col gap-1 items-end" data-testid="user-bubble">
            <div className="max-w-[85%] whitespace-pre-wrap rounded-md border border-border bg-muted px-3 py-2 font-body text-sm">
              {sentPrompt}
            </div>
          </div>
        )}

        {currentTurnId && (
          <div
            className="flex flex-col gap-2 items-start"
            data-testid="assistant-bubble"
          >
            {stream.tools.length > 0 && (
              <ul
                className="flex flex-col gap-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground"
                aria-label="Tools used"
              >
                {stream.tools.map((tool, i) => (
                  <li
                    key={i}
                    className="flex items-center gap-2"
                    data-tool-status={tool.status}
                  >
                    <span
                      className={
                        tool.status === "running"
                          ? "h-1.5 w-1.5 animate-pulse rounded-full bg-primary"
                          : tool.status === "ok"
                            ? "h-1.5 w-1.5 rounded-full bg-primary"
                            : "h-1.5 w-1.5 rounded-full bg-destructive"
                      }
                      aria-hidden
                    />
                    <span>{tool.tool}</span>
                    {typeof tool.latency_ms === "number" && (
                      <span className="tabular-nums text-muted-foreground/70">
                        {Math.round(tool.latency_ms)} ms
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {stream.text && (
              <div
                className="max-w-[85%] whitespace-pre-wrap rounded-md border border-border px-3 py-2 font-body text-sm"
                aria-live="polite"
                aria-atomic="false"
              >
                {/* Strip the [L:<lesson_id>] wire tokens during streaming
                    — the citation list is delivered AFTER the stream
                    finishes (in the persisted TutorMessageOut), so there
                    are no indices to anchor numbered references to yet.
                    The post-stream render via <TutorMessage> shows the
                    full numbered version. */}
                {renderTutorBody(stream.text, [])}
                {stream.phase === "synth" && (
                  <span
                    className="ms-1 inline-block h-3 w-1 animate-pulse bg-primary align-middle"
                    aria-hidden
                  />
                )}
              </div>
            )}

            {stream.phase === "failed" && isCostCapError(stream.error) ? (
              <CostCapClosingCta />
            ) : stream.phase === "failed" ? (
              <p className="font-body text-sm text-destructive" role="alert">
                {t("tutor.sendError")} ({stream.error ?? "unknown"})
              </p>
            ) : null}

            {stream.phase === "trim" && (
              <p className="font-body text-sm text-muted-foreground" role="status">
                {/* Tells the user the resume offset was trimmed; the
                    L23 retry CTA lands a "refresh from history" hook
                    next loop. */}
                {t("tutor.thinking")}…
              </p>
            )}
          </div>
        )}

        {sendMut.isPending && (
          <div
            className="flex items-center gap-2 font-mono text-xs text-muted-foreground"
            data-testid="streaming-tutor-loading"
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            <span>{t("tutor.thinking")}</span>
          </div>
        )}
      </div>

      <form
        className="flex items-end gap-2 border-t border-border p-3"
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
      >
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder={t("tutor.composerPlaceholder")}
          aria-label={t("tutor.composerPlaceholder")}
          rows={2}
          className="min-h-[64px] resize-none font-body text-sm"
          disabled={isInFlight}
        />
        <Button
          type="submit"
          aria-label={t("tutor.send")}
          disabled={!draft.trim() || isInFlight}
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
