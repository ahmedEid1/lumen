"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Loader2, MessageSquarePlus, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  AgentReasoningPanel,
  type ToolCallTrace,
} from "@/components/tutor/agent-reasoning-panel";
import { StreamingTutorPanel } from "@/components/tutor/streaming-tutor-panel";
import { DemoQuestionChipRail } from "@/components/tutor/demo-question-chip-rail";
import {
  Tutor,
  type TutorConversationDetail,
  type TutorMessageOut,
  type TutorPostResponse,
} from "@/lib/api/endpoints";
import { useT } from "@/lib/i18n/provider";
import { useRuntimeFlags } from "@/lib/runtime-flags";
import { supportsStreaming } from "@/lib/tutor/supports-streaming";
import { cn } from "@/lib/utils";

/**
 * Phase I2 — per-assistant-turn metadata produced by the multi-agent
 * orchestrator. Keyed by the assistant message id so the
 * ``AgentReasoningPanel`` can render under each assistant bubble
 * without re-fetching the conversation. The map lives in component
 * state because the persisted ``tutor_messages`` row doesn't carry
 * the trace — it lands only in the POST response.
 */
export type TraceMeta = {
  toolCalls: ToolCallTrace[];
  confidence: number;
};

/**
 * Tutor panel — course-scoped RAG chat surface (Phase E1).
 *
 * Workbench visual language:
 * - Surface-1 card with a thin border; mono caption + display title.
 * - Mono timestamps and lesson ids; body text in the body face.
 * - Single lime CTA (the Send button). Citations render as outline
 *   pills that gain a lime fill on hover — they're navigation, not
 *   the primary action, so they stay quiet by default.
 *
 * Behaviour:
 * - On mount we open a fresh conversation. The host page chooses
 *   when to mount us (it's an explicit "Ask the tutor" toggle), so
 *   "mounted = active" is the right reading.
 * - Optimistic UI: the user message lands in local state the
 *   instant they hit Send. We don't roll it back on error — the
 *   error toast tells them to retry and the durable POST will land
 *   the next time it succeeds. This matches what the backend already
 *   does (the user turn is persisted before the LLM call so the
 *   audit log shows what they asked even if the model errors).
 * - The composer is disabled while a request is in flight. Pressing
 *   Enter sends; Shift+Enter inserts a newline.
 */
export interface TutorPanelProps {
  courseId: string;
  /** Optional override for the host's heading text. */
  heading?: string;
  /**
   * L20.5 — optional initial composer text. Used by the `/demo`
   * deep-link to prefill the canonical demo question (`Type 'string'
   * is not assignable to type 'T'`) so a recruiter who lands on /demo
   * sees the question already in the textarea and just hits Send.
   * Only honoured on mount; later state changes from the user win.
   */
  initialDraft?: string;
  /**
   * L22 — optional course slug for the demo-question chip rail. When
   * present, the rail filters to questions scoped to this course
   * (plus global refusal probes). When absent, the full library
   * renders.
   */
  courseSlug?: string;
}

export function TutorPanel(props: TutorPanelProps) {
  // L21b — branch on runtime flag + iOS UA support. When the flag is
  // ON and the browser actually streams (iOS Safari < 15.4 fails the
  // detect), mount the SSE-backed panel. Otherwise fall through to
  // the legacy non-streaming implementation below.
  const flags = useRuntimeFlags();
  if (flags.tutor_streaming && supportsStreaming()) {
    return <StreamingTutorPanel {...props} />;
  }
  return <LegacyTutorPanel {...props} />;
}

function LegacyTutorPanel({ courseId, heading, initialDraft, courseSlug }: TutorPanelProps) {
  const t = useT();
  const qc = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [draft, setDraft] = useState(initialDraft ?? "");
  // Local optimistic messages — the user message lands here the
  // moment they hit Send, before the server round-trip lands. The
  // canonical persisted rows come back from the POST response and
  // we replace optimistic-then with server-rows.
  const [localMessages, setLocalMessages] = useState<TutorMessageOut[]>([]);
  // Phase I2 — per-assistant-message trace metadata. Keyed by the
  // server's message id; the first assistant turn after page load
  // auto-expands so a recruiter sees the agent thinking immediately.
  const [traceByMsgId, setTraceByMsgId] = useState<Record<string, TraceMeta>>(
    {},
  );
  const [firstAutoExpandedMsgId, setFirstAutoExpandedMsgId] = useState<
    string | null
  >(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Open a conversation when the panel mounts. We persist the
  // conversation id locally so re-opening the panel (or remounting
  // mid-session) doesn't lose context. A future iteration may add
  // a "switch conversation" picker; today the panel always starts
  // fresh on mount.
  const startMut = useMutation({
    mutationFn: () => Tutor.startConversation(courseId),
    onSuccess: (conv: TutorConversationDetail) => {
      setConversationId(conv.id);
      setLocalMessages(conv.messages);
    },
    onError: (e: Error) => toast.error(e?.message ?? t("tutor.startError")),
  });

  useEffect(() => {
    if (!conversationId && !startMut.isPending) {
      startMut.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  // We also load any prior turns when the panel reopens against an
  // existing conversation id. Today this is a no-op because we start
  // fresh on every mount, but the query is wired so a future
  // "resume conversation" surface drops in cleanly.
  useQuery({
    queryKey: ["tutor", "conversation", conversationId],
    queryFn: () =>
      conversationId
        ? Tutor.getConversation(conversationId)
        : Promise.resolve(null),
    enabled: !!conversationId,
  });

  const sendMut = useMutation({
    mutationFn: (content: string) =>
      Tutor.postMessage(conversationId!, content),
    onSuccess: (resp: TutorPostResponse) => {
      setLocalMessages((prev) => {
        // Drop the optimistic placeholder we appended on send, then
        // push both canonical turns in their server-blessed order.
        const withoutOptimistic = prev.filter((m) => !m.id.startsWith("opt_"));
        return [...withoutOptimistic, resp.user_message, resp.assistant_message];
      });
      // Phase I2 — stash the trace + confidence keyed by the
      // assistant message id so the reasoning panel can render
      // under that bubble. The first assistant turn after the panel
      // mounts auto-expands; later turns stay collapsed for a
      // quieter UX.
      if (resp.agent_trace && resp.agent_trace.length > 0) {
        setTraceByMsgId((prev) => ({
          ...prev,
          [resp.assistant_message.id]: {
            toolCalls: resp.agent_trace ?? [],
            confidence: resp.confidence ?? 0,
          },
        }));
        setFirstAutoExpandedMsgId((prev) =>
          prev ?? resp.assistant_message.id,
        );
      }
      qc.invalidateQueries({
        queryKey: ["tutor", "conversation", conversationId],
      });
    },
    onError: (e: Error) => toast.error(e?.message ?? t("tutor.sendError")),
  });

  // Auto-scroll to the latest turn whenever messages change.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [localMessages.length, sendMut.isPending]);

  function handleSend(textOverride?: string) {
    const text = (textOverride ?? draft).trim();
    if (!text || !conversationId || sendMut.isPending) return;
    setDraft("");
    const optimistic: TutorMessageOut = {
      id: `opt_${Date.now()}`,
      role: "user",
      content: text,
      citations: [],
      created_at: new Date().toISOString(),
    };
    setLocalMessages((prev) => [...prev, optimistic]);
    sendMut.mutate(text);
  }

  const empty = localMessages.length === 0 && !sendMut.isPending;

  return (
    <div className="surface flex h-full flex-col" data-testid="tutor-panel">
      <div className="flex items-center justify-between border-b border-border p-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {t("tutor.cartouche")}
          </p>
          <h3 className="font-display text-base leading-tight tracking-tight">
            {heading ?? t("tutor.heading")}
          </h3>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setConversationId(null);
            setLocalMessages([]);
            setTraceByMsgId({});
            setFirstAutoExpandedMsgId(null);
            startMut.mutate();
          }}
          disabled={startMut.isPending || sendMut.isPending}
          aria-label={t("tutor.newConversation")}
        >
          <MessageSquarePlus className="me-1 h-3.5 w-3.5" />
          {t("tutor.new")}
        </Button>
      </div>

      {empty && (
        <DemoQuestionChipRail
          courseSlug={courseSlug}
          onPick={(prompt) => handleSend(prompt)}
        />
      )}

      <div
        ref={scrollRef}
        className="min-h-[280px] flex-1 space-y-4 overflow-y-auto p-4"
        data-testid="tutor-messages"
      >
        {empty && (
          <div className="flex flex-col items-start gap-2 py-6 font-body text-sm text-muted-foreground">
            <Sparkles className="h-4 w-4 text-primary" aria-hidden />
            <p>{t("tutor.emptyPrompt")}</p>
          </div>
        )}
        {localMessages.map((msg) => {
          const trace = traceByMsgId[msg.id];
          return (
            <TutorMessage
              key={msg.id}
              message={msg}
              trace={trace}
              autoExpandTrace={
                trace !== undefined && msg.id === firstAutoExpandedMsgId
              }
            />
          );
        })}
        {sendMut.isPending && (
          <div
            className="flex items-center gap-2 font-mono text-xs text-muted-foreground"
            data-testid="tutor-loading"
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
          disabled={sendMut.isPending || !conversationId}
        />
        <Button
          type="submit"
          aria-label={t("tutor.send")}
          disabled={!draft.trim() || sendMut.isPending || !conversationId}
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}

/**
 * Render one turn. The role decides alignment and chrome; citations
 * only ever appear on assistant turns (the backend enforces it).
 *
 * Citation pills are rendered inline and open the linked lesson in
 * a new tab — opening in-place would replace the chat surface and
 * lose context. The pill's title attribute carries the chunk excerpt
 * for hover, but we don't render the excerpt by default to keep the
 * row compact.
 *
 * Phase I2 — assistant turns also render the
 * :class:`AgentReasoningPanel` under the bubble when the orchestrator
 * supplied a trace. The first assistant turn after the panel mounts
 * auto-expands the trace; later turns stay collapsed.
 */
function TutorMessage({
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
        {message.content}
      </div>
      {!isUser && message.citations.length > 0 && (
        <div
          className="flex flex-wrap gap-1.5 pt-1"
          data-testid="tutor-citations"
        >
          {message.citations.map((c) => (
            <a
              key={c.lesson_id}
              href={`/courses/lessons/${c.lesson_id}`}
              target="_blank"
              rel="noreferrer"
              title={c.chunk_excerpt}
              className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono text-[11px] text-primary transition-colors duration-[160ms] hover:bg-primary hover:text-primary-foreground"
            >
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
