"use client";

/**
 * One persisted tutor turn — shared by the legacy panel (live + history)
 * and the streaming panel (history rows on reopen). Extracted from
 * tutor-panel.tsx for the streaming-story loop so both panels render
 * persisted messages identically.
 *
 * The role decides alignment and chrome; citations only ever appear on
 * assistant turns (the backend enforces it). Citation pills open the
 * linked lesson in a new tab — opening in-place would replace the chat
 * surface and lose context. The pill's title attribute carries the
 * chunk excerpt for hover.
 *
 * Phase I2 — assistant turns also render the
 * :class:`AgentReasoningPanel` under the bubble when the orchestrator
 * supplied a trace. Persisted history rows never have one (the trace
 * meta only rides the live POST response), so history renders bubble +
 * citations + timestamp only.
 */

import {
  AgentReasoningPanel,
  type ToolCallTrace,
} from "@/components/tutor/agent-reasoning-panel";
import type { TutorMessageOut } from "@/lib/api/endpoints";
import { useT } from "@/lib/i18n/provider";
import { renderTutorBody } from "@/lib/tutor/citations";
import { cn } from "@/lib/utils";

export type TraceMeta = {
  toolCalls: ToolCallTrace[];
  confidence: number;
};

export function TutorMessage({
  message,
  trace,
  autoExpandTrace,
}: {
  message: TutorMessageOut;
  trace?: TraceMeta;
  autoExpandTrace?: boolean;
}) {
  const t = useT();
  const isUser = message.role === "user";
  return (
    <div
      className={cn(
        "flex flex-col gap-1",
        isUser ? "items-end" : "items-start",
      )}
      data-testid={`tutor-message-${message.role}`}
    >
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-md border px-3 py-2 font-body text-sm",
          isUser
            ? "border-foreground/20 bg-muted text-foreground"
            : "border-border bg-background text-foreground",
        )}
      >
        {isUser ? message.content : renderTutorBody(message.content, message.citations)}
      </div>
      {!isUser && message.citations.length > 0 && (
        <div
          className="flex flex-wrap gap-1.5 pt-1"
          data-testid="tutor-citations"
        >
          {message.citations.map((c, i) => (
            <a
              key={c.lesson_id}
              id={`tutor-cite-${i + 1}`}
              href={`/courses/lessons/${c.lesson_id}`}
              target="_blank"
              rel="noreferrer"
              title={c.chunk_excerpt}
              className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary transition-colors duration-[160ms] hover:bg-primary hover:text-primary-foreground"
            >
              <span aria-hidden className="font-mono">[{i + 1}]</span>
              {c.lesson_title}
            </a>
          ))}
        </div>
      )}
      {!isUser && trace && trace.toolCalls.length > 0 && (
        <div className="w-full max-w-[85%]">
          <AgentReasoningPanel
            toolCalls={trace.toolCalls}
            confidence={trace.confidence}
            defaultExpanded={autoExpandTrace}
          />
        </div>
      )}
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
        {isUser ? t("tutor.you") : t("tutor.assistant")} ·{" "}
        {new Date(message.created_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </p>
    </div>
  );
}
